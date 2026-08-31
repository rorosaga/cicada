import SwiftUI

/// The range + detail pickers, hoisted out of the page header so `ActivityView`
/// can host them next to the section picker.
struct UsageRangeControls: View {
    let viewModel: UsageViewModel

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            // `labelsHidden` + `fixedSize`: a fixed 130/180 pt frame
            // truncated the menu title to "This…" and wrapped the
            // segmented control to "Mo de".
            Picker("Range", selection: Binding(get: { viewModel.range }, set: { viewModel.range = $0 })) {
                Text("This month").tag("month")
                Text("30 days").tag("30d")
                Text("90 days").tag("90d")
                Text("All time").tag("all")
            }
            .pickerStyle(.menu).labelsHidden().fixedSize()
            .accessibilityLabel("Choose the reporting range")

            Picker("Mode", selection: Binding(get: { viewModel.mode }, set: { viewModel.mode = $0 })) {
                ForEach(UsageMode.allCases, id: \.self) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented).labelsHidden().fixedSize()
            .accessibilityLabel("Choose how much detail to show")

            if viewModel.isLoadingRange { ProgressView().controlSize(.small) }
        }
    }
}

/// G51 — consumption & traceability. Minimal: four tiles + calendar.
/// Advanced: per-connection cost, charts, tables, /stats-style facts.
///
/// `UsageViewModel` is a thin projection over `Store.consumption` (§5.5),
/// constructed once in `CicadaApp.init()` and injected via `.environment`
/// like every other screen's view model (`ContributorsViewModel`,
/// `ConnectionsViewModel`) — this view never talks to `APIClient` directly.
///
/// The Usage half of the Activity page (G51 §3.9). No page header of its own —
/// `ActivityView` owns the title, the section picker and the range controls.
struct UsageSection: View {
    @Environment(UsageViewModel.self) private var viewModel
    /// The Store already hydrates and refreshes `.consumption`; this reconcile
    /// is a one-shot, not a per-appear refetch (§5.5).
    @State private var loadedOnce = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if let err = viewModel.errorMessage {
                Text(err).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.statusColor(for: .decaying))
            }

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    tiles
                    HeatmapView(days: viewModel.calendar, selected: Binding(get: { viewModel.selectedDay }, set: { viewModel.selectedDay = $0 }))
                    if let day = viewModel.selectedDay { dayDetail(day) }
                    connectionsLine
                    if viewModel.mode == .advanced {
                        UsageAdvancedView(viewModel: viewModel)
                    }
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await viewModel.load()
        }
    }

    @ViewBuilder
    private var tiles: some View {
        if viewModel.isEmptyRange {
            placeholder("No usage in this range")
        } else {
            HStack(spacing: CicadaTheme.spacingMD) {
                StatTile(title: viewModel.range == "month" ? "This month" : "Cost",
                         value: viewModel.subscriptionUsdMonth != nil && viewModel.summary.costUsd == 0
                            ? "Included" : UsageFormat.usd(viewModel.summary.costUsd),
                         footnote: viewModel.costLine)
                StatTile(title: "Memory writes", value: UsageFormat.count(viewModel.summary.memoryWrites),
                         footnote: "\(UsageFormat.count(viewModel.summary.agenticWrites)) in-session · \(UsageFormat.count(viewModel.summary.sleepRuns)) sleep runs")
                StatTile(title: "Tokens", value: UsageFormat.tokens(viewModel.summary.tokens),
                         footnote: "\(UsageFormat.count(viewModel.summary.invocations)) invocations")
                StatTile(title: "Streak", value: "\(viewModel.summary.streakCurrent)d",
                         footnote: "best \(viewModel.summary.streakBest)d")
            }
        }
    }

    func placeholder(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(CicadaTheme.spacingLG)
            .glassCard()
    }

    private func dayDetail(_ d: CalendarDay) -> some View {
        HStack(spacing: CicadaTheme.spacingLG) {
            Text(d.date).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            Label("\(d.memoryWrites) memory writes", systemImage: "square.and.pencil")
            Label("\(d.events) events", systemImage: "bolt")
            Label("\(UsageFormat.tokens(d.tokens)) tokens", systemImage: "number")
            Label(d.costUsd > 0 ? "\(UsageFormat.usd(d.costUsd)) spent" : "≈ \(UsageFormat.usd(d.equivCostUsd)) API-equivalent", systemImage: "dollarsign.circle")
            Spacer()
        }
        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
        .padding(CicadaTheme.spacingMD).glassCard()
    }

    private var connectionsLine: some View {
        let parts = viewModel.connections.filter(\.connected).map { c -> String in
            switch c.billing {
            case "subscription": c.priceUsdMonth.map { "\(c.label) · $\(Int($0))/mo" } ?? c.label
            case "free": "\(c.label) · free"
            default: "\(c.label) · \(UsageFormat.usd(c.costUsd)) \(viewModel.range == "month" ? "this month" : "in range")"
            }
        }
        return Text(parts.isEmpty ? Copy.noConnections : "Connections: " + parts.joined(separator: " · "))
            .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
    }
}

struct StatTile: View {
    let title: String
    let value: String
    var footnote: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(title).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            Text(value).font(CicadaTheme.titleFont).foregroundStyle(CicadaTheme.textPrimary)
            if let footnote { Text(footnote).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(2) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .glassCard()
    }
}
