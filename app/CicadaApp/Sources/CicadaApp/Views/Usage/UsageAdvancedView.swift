import Charts
import SwiftUI

/// Advanced Usage view (§3.9): per-connection cost cards, charts, tables,
/// /stats-style facts, and the harness panel. Pure view code over
/// `UsageViewModel`'s Store-backed projections (`stats`/`connections`/`harness`).
struct UsageAdvancedView: View {
    let viewModel: UsageViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            connectionCards
            if let stats = viewModel.stats {
                charts(stats)
                facts(stats)
                table("By model", rows: stats.byModel)
                table("By stage", rows: stats.byStage)
                table("By bank", rows: stats.byBank)
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }
            harnessPanel
        }
    }

    // MARK: connections

    private var connectionCards: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            sectionTitle("Connections")
            ForEach(viewModel.connections.filter { $0.connected || $0.tokens > 0 }) { c in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    HStack {
                        Text(c.label).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                        Spacer()
                        Text(priceText(c)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                    }
                    Text(detailText(c)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    if c.throttleEvents > 0 {
                        Text("Throttled \(c.throttleEvents)× in range — Cicada stopped and resumed the next night.")
                            .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.statusColor(for: .decaying))
                    }
                    if !c.byModel.isEmpty {
                        ForEach(c.byModel) { m in
                            HStack {
                                Text(m.name).font(CicadaTheme.monoFont)
                                Spacer()
                                Text("\(UsageFormat.tokens(m.tokens)) tok")
                                Text(c.billing == "usage" ? UsageFormat.usd(m.costUsd) : "≈ \(UsageFormat.usd(m.equivCostUsd))").frame(width: 90, alignment: .trailing)
                            }
                            .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                        }
                    }
                }
                .padding(CicadaTheme.spacingMD).glassCard()
            }
        }
    }

    private func priceText(_ c: ConnectionConsumption) -> String {
        switch c.billing {
        case "subscription": c.priceUsdMonth.map { "$\(Int($0))/mo" } ?? "plan"
        case "free": "free"
        default: UsageFormat.usd(c.costUsd) + " spent"
        }
    }

    private func detailText(_ c: ConnectionConsumption) -> String {
        switch c.billing {
        case "subscription": "\(c.invocations) invocations · \(UsageFormat.tokens(c.tokens)) tokens · ≈ \(UsageFormat.usd(c.equivCostUsd)) at API list price (estimate — not billed)"
        case "free": "\(c.invocations) invocations · \(UsageFormat.tokens(c.tokens)) tokens · on-device"
        default: "\(c.invocations) invocations · \(UsageFormat.tokens(c.tokens)) tokens · real cost from provider list prices"
        }
    }

    // MARK: charts

    private func charts(_ s: ConsumptionStats) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            chartCard("Tokens per day") {
                Chart(s.series) { p in
                    BarMark(x: .value("Day", p.date), y: .value("Tokens", p.tokens)).foregroundStyle(CicadaTheme.accent)
                }
                .chartXAxis { AxisMarks(values: .automatic(desiredCount: 6)) { _ in AxisValueLabel() } }
            }
            chartCard("Cost per day") {
                Chart(s.series) { p in
                    BarMark(x: .value("Day", p.date), y: .value("Spent", p.costUsd)).foregroundStyle(CicadaTheme.accent)
                    LineMark(x: .value("Day", p.date), y: .value("API-equivalent", p.equivCostUsd)).foregroundStyle(CicadaTheme.textTertiary)
                }
                .chartXAxis { AxisMarks(values: .automatic(desiredCount: 6)) { _ in AxisValueLabel() } }
            }
            chartCard("Hour of day") {
                Chart(Array(s.hourHistogram.enumerated()), id: \.offset) { h in
                    BarMark(x: .value("Hour", h.offset), y: .value("Events", h.element)).foregroundStyle(CicadaTheme.accent.opacity(0.7))
                }
            }
        }
        .frame(height: 180)
    }

    private func chartCard<C: View>(_ title: String, @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(title).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            content()
        }
        .frame(maxWidth: .infinity).padding(CicadaTheme.spacingMD).glassCard()
    }

    // MARK: /stats-style facts

    private func facts(_ s: ConsumptionStats) -> some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            StatTile(title: "Lifetime tokens", value: UsageFormat.tokens(s.lifetimeTokens), footnote: s.firstEvent.map { "since \($0)" })
            StatTile(title: "Favorite model", value: s.favoriteModel ?? "—", footnote: "most tokens in range")
            StatTile(title: "Peak day", value: s.peakDay?["date"]?.text ?? "—", footnote: s.peakDay?["tokens"]?.number.map { "\(UsageFormat.tokens(Int($0))) tokens" })
            StatTile(title: "Longest sleep run",
                     value: s.longestSleepRun?["duration_ms"]?.number.map { "\(Int($0 / 60000))m" } ?? "—",
                     footnote: s.longestSleepRun?["episodes_processed"]?.number.map { "\(Int($0)) episodes" })
        }
    }

    // MARK: tables

    private func table(_ title: String, rows: [StatsRow]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            sectionTitle(title)
            Grid(alignment: .leading, horizontalSpacing: CicadaTheme.spacingMD, verticalSpacing: 4) {
                GridRow {
                    Text("Name"); Text("Calls"); Text("In"); Text("Out"); Text("Cache"); Text("Spent"); Text("≈ API")
                }
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                ForEach(rows) { r in
                    GridRow {
                        Text(r.name).font(CicadaTheme.monoFont)
                        Text("\(r.invocations)")
                        Text(UsageFormat.tokens(r.inputTokens))
                        Text(UsageFormat.tokens(r.outputTokens))
                        Text(UsageFormat.tokens(r.cacheReadTokens + r.cacheWriteTokens))
                        Text(UsageFormat.usd(r.costUsd))
                        Text(UsageFormat.usd(r.equivCostUsd))
                    }
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            .padding(CicadaTheme.spacingMD).glassCard()
        }
    }

    // MARK: harness (Claude Code's own stats + Codex rate-limit snapshot)

    @ViewBuilder
    private var harnessPanel: some View {
        if let h = viewModel.harness, h.claudeCode != nil || h.codex != nil {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                sectionTitle("Your agent harnesses (their own data, not Cicada's)")
                if let cc = h.claudeCode {
                    HStack(spacing: CicadaTheme.spacingMD) {
                        StatTile(title: "Claude Code sessions", value: cc["total_sessions"]?.value?.text ?? "—", footnote: "from ~/.claude/stats-cache.json")
                        StatTile(title: "Claude Code messages", value: cc["total_messages"]?.value?.text ?? "—", footnote: cc["first_session_date"]?.value.map { "since \($0.text)" })
                    }
                }
                if let cx = h.codex {
                    let primary = cx["primary"]?["used_percent"]?.value?.number
                    let secondary = cx["secondary"]?["used_percent"]?.value?.number
                    HStack(spacing: CicadaTheme.spacingMD) {
                        StatTile(title: "Codex 5-hour window", value: primary.map { "\(Int($0))%" } ?? "—", footnote: "last snapshot in ~/.codex/sessions")
                        StatTile(title: "Codex weekly window", value: secondary.map { "\(Int($0))%" } ?? "—", footnote: cx["plan_type"]?.value.map { "plan: \($0.text)" })
                    }
                }
                Text("No rate-limit figures are shown for Claude: there is no compliant local source. Cicada reports the throttle events it observed instead.")
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    private func sectionTitle(_ t: String) -> some View {
        Text(t).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
    }
}
