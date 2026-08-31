import SwiftUI

/// G51 — consumption & traceability. Minimal: four tiles + calendar.
/// Advanced: per-connection cost, charts, tables, /stats-style facts.
///
/// `UsageViewModel` is a thin projection over `Store.consumption` (§5.5),
/// constructed once in `CicadaApp.init()` and injected via `.environment`
/// like every other screen's view model (`ContributorsViewModel`,
/// `ConnectionsViewModel`) — this view never talks to `APIClient` directly.
struct UsageView: View {
    @Environment(UsageViewModel.self) private var viewModel

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            PageHeader(title: "Usage", subtitle: "What Cicada consumed, on which connection, at what price.") {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Picker("Range", selection: Binding(get: { viewModel.range }, set: { viewModel.range = $0 })) {
                        Text("This month").tag("month"); Text("30 days").tag("30d"); Text("90 days").tag("90d"); Text("All time").tag("all")
                    }
                    .pickerStyle(.menu).frame(width: 130)
                    Picker("Mode", selection: Binding(get: { viewModel.mode }, set: { viewModel.mode = $0 })) {
                        ForEach(UsageMode.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented).frame(width: 180)
                }
            }

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
        .padding(CicadaTheme.spacingLG)
        .task { await viewModel.load() }
    }

    private var tiles: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            StatTile(title: viewModel.range == "month" ? "This month" : "Cost", value: viewModel.subscriptionUsdMonth != nil && viewModel.summary.costUsd == 0
                     ? "Included" : UsageFormat.usd(viewModel.summary.costUsd), footnote: viewModel.costLine)
            StatTile(title: "Memory writes", value: "\(viewModel.summary.memoryWrites)", footnote: "\(viewModel.summary.agenticWrites) in-session · \(viewModel.summary.sleepRuns) sleep runs")
            StatTile(title: "Tokens", value: UsageFormat.tokens(viewModel.summary.tokens), footnote: "\(viewModel.summary.invocations) invocations")
            StatTile(title: "Streak", value: "\(viewModel.summary.streakCurrent)d", footnote: "best \(viewModel.summary.streakBest)d")
        }
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
