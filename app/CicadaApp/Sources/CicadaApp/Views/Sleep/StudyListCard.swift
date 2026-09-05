import SwiftUI

/// "What is waiting for the next cycle", grouped by source (G125 — replaces
/// the old `SleepQueueCard` + `SleepDebtBreakdown` pair, R1/R11). One row per
/// origin, largest pile first; a chevron discloses that origin's episodes
/// inline; the footer names when the next run happens. The one
/// Consolidate/Cancel control lives in the hero since G125 v3 (R-A7) — the
/// ruling is still "exactly one on this page", only its home moved.
///
/// A projection over `Store.status` plus `SleepViewModel`; starts no fetches
/// of its own. `rows` is computed by the caller (`studyRows`, in
/// `SleepQueueModel.swift`) so this view stays a pure renderer of whatever
/// the desk card already resolved SSE-vs-REST precedence for.
struct StudyListCard: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    let rows: [StudyRow]
    let episodes: [EpisodeQueueItem]
    var onSelectEntity: ((String) -> Void)?

    /// Which origins are disclosed. Local UI state, not persisted — a fresh
    /// visit to the page starts every row collapsed.
    @State private var expandedOrigins: Set<String> = []

    private var status: StatusSnapshot? { store.status.value }
    private var isLoading: Bool { store.status.isEmpty && store.status.isRefreshing }

    /// PR #19 review (moved verbatim from `SleepQueueCard`, R11): a missing
    /// `store.status` is not one state, it's two — a fetch still in flight
    /// (`.loading`) vs. one that already failed and left nothing behind
    /// (`.failed`) — and neither is "a confirmed zero queue"
    /// (`.loaded(count: 0)`, the only case that state may render for).
    enum LoadState: Equatable {
        case loading
        case failed(String)
        case loaded(count: Int)
    }

    static func loadState(status: StatusSnapshot?, isLoading: Bool, error: String?) -> LoadState {
        if let status { return .loaded(count: status.episodes.unprocessed) }
        if isLoading { return .loading }
        if let error { return .failed(error) }
        // No snapshot, not refreshing, no latched failure yet — the fetch
        // simply hasn't started. Treat like loading rather than guessing.
        return .loading
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("ON THE DESK")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            content

            Divider().background(CicadaTheme.border).padding(.vertical, CicadaTheme.spacingXS)

            // R-A7 (upgrading G125 R10): the one Consolidate/Cancel control
            // moved to the hero, where the decision is actually made — the
            // count, the meter and the engine it would run on are all right
            // there. This footer keeps only the line that says WHEN the next
            // run happens without anyone clicking anything.
            HStack(spacing: CicadaTheme.spacingMD) {
                nextRunLine
                Spacer()
            }

            if let err = sleepVM.errorMessage ?? sleepVM.lastError, !err.isEmpty {
                Text(err)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    @ViewBuilder
    private var content: some View {
        switch Self.loadState(status: status, isLoading: isLoading, error: store.domainErrors[.status]) {
        case .loading:
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Checking the queue…")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        case .failed(let message):
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "exclamationmark.triangle")
                    .font(CicadaTheme.font(size: 12))
                    .foregroundStyle(CicadaTheme.danger)
                Text(message)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                Spacer()
                Button("Retry") { Task { await store.refresh([.status]) } }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.accent)
                    .accessibilityLabel("Retry loading the queue")
            }
        case .loaded(let count):
            if rows.isEmpty {
                Text(count == 0 ? "All caught up" : "Nothing grouped yet.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.vertical, CicadaTheme.spacingSM)
            } else {
                LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(rows) { row in
                        rowView(row)
                        if expandedOrigins.contains(row.origin) {
                            LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                                ForEach(episodesForOrigin(row.origin)) { ep in
                                    EpisodeRow(item: ep)
                                }
                            }
                            .padding(.leading, CicadaTheme.spacingLG)
                        }
                    }
                }
            }
        }
    }

    private func rowView(_ row: StudyRow) -> some View {
        Button {
            withAnimation(.easeInOut(duration: 0.15)) {
                if expandedOrigins.contains(row.origin) {
                    expandedOrigins.remove(row.origin)
                } else {
                    expandedOrigins.insert(row.origin)
                }
            }
        } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: expandedOrigins.contains(row.origin) ? "chevron.down" : "chevron.right")
                    .font(CicadaTheme.font(size: 9, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(width: 10)

                OriginMark(origin: row.origin, size: 18)

                VStack(alignment: .leading, spacing: 1) {
                    Text(row.label)
                        .font(CicadaTheme.font(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    if let age = row.oldestAge {
                        Text("oldest \(age)")
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }

                Spacer()

                trailing(row)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityLabel("\(row.label), \(row.count) queued")
    }

    /// While idle: the plain count. While running: `read / total`, unless
    /// this source was left out of the cycle by the episode cap — signaled
    /// by `total == 0` (`studyRows`'s own doc comment) — in which case
    /// "next cycle" is the honest read rather than a bogus "0 of 0".
    @ViewBuilder
    private func trailing(_ row: StudyRow) -> some View {
        if let total = row.total, let read = row.read {
            if total == 0 {
                Text("next cycle")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text("\(read) / \(total)")
                        .font(CicadaTheme.font(size: 12, weight: .semibold, design: .rounded))
                        .foregroundStyle(CicadaTheme.textSecondary)
                    ProgressView(value: Double(read), total: Double(total))
                        .frame(width: 60)
                }
            }
        } else {
            Text("\(row.count)")
                .font(CicadaTheme.font(size: 12, weight: .semibold, design: .rounded))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
    }

    private func episodesForOrigin(_ origin: String) -> [EpisodeQueueItem] {
        episodes
            .filter { $0.origin == origin }
            .sorted {
                (parseEpisodeTimestamp($0.timestamp) ?? .distantPast)
                    > (parseEpisodeTimestamp($1.timestamp) ?? .distantPast)
            }
    }

    // MARK: Footer — when the next run happens

    /// "Manual only" / "Next run …" / "… after the next import", with a
    /// pointer to Settings → Sleep — the one place the time/interval
    /// itself is edited (no picker duplicated here).
    private var nextRunLine: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text(nextRunText)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            SettingsLink {
                Text(Copy.changeInSettingsSleep)
            }
            .buttonStyle(.cicadaPlain)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.accent)
        }
    }

    private var nextRunText: String {
        if sleepVM.schedule.mode == "manual" {
            return Copy.nextRunManual
        }
        guard let date = StatusSnapshot.parseDate(status?.nextSleepAt) else {
            return sleepVM.schedule.mode == "after_import" ? "Next run after the next import" : "Next run —"
        }
        let f = DateFormatter()
        f.dateFormat = "MMM d, h:mm a"
        return "Next run \(f.string(from: date))"
    }
}
