import SwiftUI

/// Pure labels for the per-source queue strip (Track D), tested without a
/// view: "N waiting for Sleep", and the "consolidated so far" line, which
/// counts conversations for a harness and captures for everything else —
/// the same distinction `SourceOverview.countLines` already draws.
enum SourceQueueLabels {
    static func waiting(_ count: Int) -> String {
        count == 0 ? "Nothing waiting for Sleep" : "\(count) waiting for Sleep"
    }

    /// `nil` when there's nothing to report yet ("hidden when both are 0") —
    /// a fresh source with an empty queue and no history shouldn't print
    /// "0 captures → 0 entities".
    static func consolidatedSoFar(for source: SourceOverview) -> String? {
        let (n, unit): (Int, String) = source.kind == .harness
            ? (source.conversations, "conversation")
            : (source.episodes, "capture")
        guard n > 0 || source.entities > 0 else { return nil }
        let left = "\(n) \(unit)\(n == 1 ? "" : "s")"
        let right = "\(source.entities) \(source.entities == 1 ? "entity" : "entities")"
        return "Consolidated so far: \(left) → \(right)"
    }
}

/// "N waiting for Sleep" + Consolidate now, and what has already been folded
/// in — the per-source page's queue strip (Track D). A pure projection over
/// `SleepViewModel.queuedEpisodes` (filtered to this source by
/// `SourceOverview.ownedQueue`) and the overview row's own counts; starts no
/// fetches of its own — `SourceDetailView` calls `sleepVM.load()` once so
/// `queuedEpisodes` is populated even when a person opens Sources without
/// ever visiting Sleep first this session.
struct SourceQueueStrip: View {
    let source: SourceOverview

    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    private var owned: [EpisodeQueueItem] { source.ownedQueue(from: sleepVM.queuedEpisodes) }

    /// `source` is a snapshot captured at navigation time (`SourcesPageView`'s
    /// `route` holds it in a plain `let`, never re-derived) — after a
    /// Consolidate run its counts are stale even though `store.sourcesOverview`
    /// just refreshed. Re-resolve against the live snapshot by id on every
    /// render so "consolidated so far" moves the moment Sleep finishes,
    /// falling back to the captured value only when the row has aged out of
    /// the overview (deleted source, still-loading snapshot).
    private var liveSource: SourceOverview {
        store.sourcesOverview.value?.first(where: { $0.id == source.id }) ?? source
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingMD) {
                Text(SourceQueueLabels.waiting(owned.count))
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                consolidateButton
            }
            if let line = SourceQueueLabels.consolidatedSoFar(for: liveSource) {
                Text(line)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(CicadaTheme.spacingMD)
        .glassCard()
        .padding(.horizontal, CicadaTheme.spacingXL)
        .padding(.top, CicadaTheme.spacingSM)
    }

    /// The same capsule the Sleep page's queue card uses — moon icon, accent
    /// when there's something to do, grey and disabled when idle and empty.
    /// Duplicated rather than imported (R-D7): `SleepQueueCard` is Track A's
    /// file, being rebuilt into the study desk on a parallel worktree right
    /// now, and sharing a symbol across two in-flight branches over a file
    /// neither otherwise touches is exactly the merge collision
    /// `working-method.md` keeps tracks apart to avoid.
    private var consolidateButton: some View {
        Button {
            Task {
                await sleepVM.triggerManually()
                await store.refresh([.status, .channels, .sourcesOverview])
            }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                if sleepVM.isRunning {
                    ProgressView().controlSize(.small).frame(width: 12, height: 12)
                } else {
                    Image(systemName: "moon.fill").font(CicadaTheme.font(size: 12))
                }
                Text(sleepVM.isRunning ? Copy.consolidating : Copy.consolidateNow)
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
            }
            .foregroundStyle(owned.isEmpty && !sleepVM.isRunning ? CicadaTheme.textTertiary : .white)
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(owned.isEmpty && !sleepVM.isRunning ? CicadaTheme.surfaceElevated : CicadaTheme.accent.opacity(0.9))
            .clipShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(sleepVM.isRunning || owned.isEmpty)
        .help(owned.isEmpty ? "Nothing queued right now" : "Run the Sleep cycle now")
        .accessibilityLabel(Copy.consolidateNow)
    }
}
