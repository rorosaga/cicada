import SwiftUI

/// A tile's content, pure so the "counts only" rule is unit-tested.
struct StatTileSpec: Equatable {
    let title: String
    let value: String
    let footnote: String?
}

/// The Advanced section of the Sources page (G124, behind the persisted
/// `UsageMode` toggle — R8). Counts only, by the 2026-09-03 ruling: memory
/// writes, sleep runs, in-session writes, streak, then the read/write stats
/// (most-written from git, most-read from the ids-only `read` ledger kind)
/// and the harness panel's own session/message counts. No cost, no tokens,
/// no per-connection cards — `/consumption/*` still serves those fields; this
/// page simply never renders them.
///
/// `UsageViewModel` is a thin projection over `Store.consumption` (§5.5),
/// constructed once in `CicadaApp.init()` and injected via `.environment`;
/// the only direct `APIClient` call here is the on-demand top-entities fetch,
/// which is range-scoped like the summary and has no Store domain.
struct AdvancedStatsView: View {
    var onSelectEntity: ((String) -> Void)?

    @Environment(UsageViewModel.self) private var viewModel
    @State private var top: TopEntities?
    @State private var topFailed = false
    /// The Store already hydrates and refreshes `.consumption`; this reconcile
    /// is a one-shot, not a per-appear refetch (§5.5).
    @State private var loadedOnce = false

    /// Pure: the four tiles from a summary. Tested to contain no `$`.
    static func tiles(for s: ConsumptionSummary) -> [StatTileSpec] {
        [
            StatTileSpec(title: "Memory writes", value: UsageFormat.count(s.memoryWrites), footnote: nil),
            StatTileSpec(title: "Sleep runs", value: UsageFormat.count(s.sleepRuns), footnote: nil),
            StatTileSpec(title: "In-session writes", value: UsageFormat.count(s.agenticWrites), footnote: "claims agents wrote mid-conversation"),
            StatTileSpec(title: "Streak", value: "\(s.streakCurrent)d", footnote: "best \(s.streakBest)d"),
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            HStack(spacing: CicadaTheme.spacingSM) {
                // `labelsHidden` + `fixedSize`: a fixed-width frame truncated
                // the menu title to "This…" on the old Usage page.
                Picker("Range", selection: Binding(get: { viewModel.range }, set: { viewModel.range = $0 })) {
                    Text("This month").tag("month"); Text("30 days").tag("30d"); Text("90 days").tag("90d"); Text("All time").tag("all")
                }
                .pickerStyle(.menu).labelsHidden().fixedSize()
                .accessibilityLabel("Choose the reporting range")
                if viewModel.isLoadingRange { ProgressView().controlSize(.small) }
            }
            // PR #19 review: before month data lands (or while another range
            // is loading), `isEmptyRange` reads `false` — `summary`'s
            // zero-valued fallback isn't a confirmed empty range — so without
            // the progress branch the tile row rendered that fallback as if
            // it were real, loaded data. `showsProgress` covers both "never
            // loaded" and "actively loading"; the error branch must come
            // next, because `showsProgress` clears the instant a fetch fails
            // (PR #19 round 4) and would otherwise fall through to zeroes.
            if viewModel.showsProgress {
                ProgressView().frame(maxWidth: .infinity, alignment: .center).padding(CicadaTheme.spacingLG)
            } else if let err = viewModel.errorMessage {
                placeholder(err)
            } else if viewModel.isEmptyRange {
                placeholder("No activity in this range")
            } else {
                HStack(spacing: CicadaTheme.spacingMD) {
                    ForEach(Self.tiles(for: viewModel.summary), id: \.title) { t in
                        StatTile(title: t.title, value: t.value, footnote: t.footnote)
                    }
                    feedbackTileSlot
                }
            }
            readWriteStats
            harnessPanel
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await viewModel.load()
            await loadTop()
        }
        .task(id: viewModel.range) { await loadTop() }
    }

    /// G113 slice 4's Feedback-rate tile (a rate, not a price — welcome under
    /// Advanced). "n/a" distinguishes "every resolution this month was a
    /// deferral" (engagement, no judgement) from "—" (no ledger data at all).
    @ViewBuilder private var feedbackTileSlot: some View {
        StatTile(title: "Feedback", value: viewModel.feedbackValue, footnote: viewModel.feedbackFootnote)
    }

    private func loadTop() async {
        do { top = try await APIClient.shared.fetchTopEntities(limit: 10, range: viewModel.range); topFailed = false }
        catch { topFailed = true }
    }

    @ViewBuilder
    private var readWriteStats: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            // R13: most-written is bounded by a commit window, so the footnote
            // says "over the last N commits" rather than implying all-time.
            entityList("Most written", footnote: top.map { "over the last \(UsageFormat.count($0.commitsScanned)) commits" },
                       rows: (top?.written ?? []).map { ($0.entityId, "\(UsageFormat.count($0.commits)) commits") })
            entityList("Most read", footnote: "opened in the app or recalled by an agent",
                       rows: (top?.read ?? []).map { ($0.entityId, "\(UsageFormat.count($0.reads)) reads") })
        }
        if topFailed {
            Text("Couldn't load read/write stats").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private func entityList(_ title: String, footnote: String?, rows: [(String, String)]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(title).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            if rows.isEmpty {
                Text("Nothing yet").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(rows, id: \.0) { id, count in
                HStack {
                    if let onSelectEntity {
                        Button(id) { onSelectEntity(id) }.buttonStyle(.cicadaPlain).foregroundStyle(CicadaTheme.accent)
                    } else {
                        Text(id).foregroundStyle(CicadaTheme.textPrimary)
                    }
                    Spacer()
                    Text(count).foregroundStyle(CicadaTheme.textTertiary)
                }
                .font(CicadaTheme.captionFont)
            }
            if let footnote { Text(footnote).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD).glassCard()
    }

    private func placeholder(_ text: String) -> some View {
        Text(text).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
            .frame(maxWidth: .infinity, alignment: .center).padding(CicadaTheme.spacingLG).glassCard()
    }

    // MARK: harness (Claude Code's own stats + Codex rate-limit snapshot)
    //
    // Moved verbatim from the deleted `UsageAdvancedView` (G124). Claude Code
    // sessions/messages come from ~/.claude/stats-cache.json — a count file,
    // never a transcript — and the Codex rate-limit windows are percentages:
    // counts and rates, never prices, so the panel survives the ruling.

    @ViewBuilder
    private var harnessPanel: some View {
        if let h = viewModel.harness, h.claudeCode != nil || h.codex != nil {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                sectionTitle("Your agent harnesses (their own data, not Cicada's)")
                if let cc = h.claudeCode {
                    HStack(spacing: CicadaTheme.spacingMD) {
                        StatTile(title: "Claude Code sessions",
                                 value: UsageFormat.harnessValue(cc["total_sessions"]?.value),
                                 footnote: "from ~/.claude/stats-cache.json")
                        StatTile(title: "Claude Code messages",
                                 value: UsageFormat.harnessValue(cc["total_messages"]?.value),
                                 footnote: cc["first_session_date"]?.value.map { "since \($0.text)" })
                    }
                }
                if let cx = h.codex {
                    let primary = cx["primary"]?["used_percent"]?.value?.number
                    let secondary = cx["secondary"]?["used_percent"]?.value?.number
                    HStack(spacing: CicadaTheme.spacingMD) {
                        StatTile(title: "Codex 5-hour window", value: UsageFormat.percent(primary),
                                 footnote: "last snapshot in ~/.codex/sessions")
                        StatTile(title: "Codex weekly window", value: UsageFormat.percent(secondary),
                                 footnote: cx["plan_type"]?.value.map { "plan: \($0.text)" })
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
