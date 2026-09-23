import SwiftUI

/// Whether Details › Last cycle has anything to say (Track Z §4.1 F). The
/// four inputs are exactly the four banners' own conditions, so the section
/// can never render as an empty header.
func lastCycleSectionIsVisible(pageError: String?, cancelled: Bool, capped: Bool, indexWarning: String?) -> Bool {
    pageError != nil || cancelled || capped || !(indexWarning ?? "").isEmpty
}

/// The page's one second surface (R-Z6, R-Z7): opened on purpose, remembered
/// per viewer (spec decision 16), and **not built while closed** — `SleepView`
/// wraps it in `if detailsOpen {}`, so a closed Details costs no queue
/// `LazyVStack`, no history and no tiles (design §10's budget).
///
/// Each section carries its `DetailsSection.anchorID`, which is how a sentence
/// tail ("it's in Details") and "See what changed ›" land on the right card.
/// R-A12: every section takes the liveness desaturation except Last cycle —
/// news stays at full contrast. The `.saturation` is applied unconditionally
/// (identity 1.0 while live) for the reason `SleepView.roomCard`'s call site
/// gives: a conditional modifier would remount the card and empty
/// `StudyListCard`'s expanded rows whenever the connection flaps.
struct SleepDetails: View {
    static let openKey = "cicada.sleep.detailsOpen"
    static let defaultOpen = false

    let page: SleepPageModel
    let liveness: SleepLiveness
    let pageError: String?
    let status: SleepStatusResponse?
    let episodes: [EpisodeQueueItem]
    let history: [SleepHistoryEntry]
    let details: [String: SleepCycleDetail]
    let expanded: String?
    let onToggleHistory: (String) -> Void
    var onSelectEntity: ((String) -> Void)?
    /// Track Z Z6 (I5, I7) — hands the room to What's waiting, so a row and
    /// its spine answer each other's hover.
    var room: RoomModel? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if lastCycleSectionIsVisible(pageError: pageError, cancelled: page.cancelled,
                                         capped: page.capped, indexWarning: page.indexWarning) {
                LastCycleSection(pageError: pageError, status: status, cancelled: page.cancelled,
                                 capped: page.capped, indexWarning: page.indexWarning)
                    .id(DetailsSection.lastCycle.anchorID)
            }
            StudyListCard(rows: page.rows, episodes: episodes, queueLoad: page.queueLoad,
                          onSelectEntity: onSelectEntity, room: room)
                .id(DetailsSection.waiting.anchorID)
                .saturation(liveness.saturation)
            SleepReadoutView(mood: page.mood, debt: page.debt, read: page.read, total: page.total,
                             lastDurationMs: page.lastCycle?.durationMs,
                             lastEngine: status?.lastEngine, engineDetail: status?.engineDetail)
                .id(DetailsSection.readout.anchorID)
                .saturation(liveness.saturation)
            ConsolidationHistoryCard(entries: history, details: details, expanded: expanded,
                                     onToggle: onToggleHistory, onSelectEntity: onSelectEntity)
                .id(DetailsSection.pastNights.anchorID)
                .saturation(liveness.saturation)
        }
    }
}

/// Details › Last cycle — today's four banners, moved verbatim from
/// `SleepView` (Track Z §4.2): the error (`pageError`), the cancel, the episode
/// cap and the index warning, at full contrast (R-A12).
///
/// Review fix L1/L4 still holds: `cancelled`/`episodeCap`/`episodesQueued`
/// were decoded but read by no view — only the free-text `progress` sentence
/// mentioned either — so each gets a real, structured readout here rather than
/// depending on the person to parse a sentence. The three conditions arrive
/// already resolved on `SleepPageModel` (the same values the sentence's tail
/// read), and the cap NUMBERS still come from the status itself.
struct LastCycleSection: View {
    let pageError: String?
    let status: SleepStatusResponse?
    let cancelled: Bool
    let capped: Bool
    let indexWarning: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("LAST CYCLE")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
            if let error = pageError {
                errorBanner(error)
            }
            if cancelled {
                cancelledBanner
            }
            if capped, let s = status {
                capBanner(processed: s.episodesTotal, queued: s.episodesQueued, cap: s.episodeCap)
            }
            // Non-fatal warnings (e.g. LEANN episode index rebuild failed
            // even though entity writes + commit succeeded). Surfaced so a
            // "completed with warnings" cycle never looks like a clean pass.
            if let warning = indexWarning {
                warningBanner(warning)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    // MARK: Error banner

    private func errorBanner(_ text: String) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(CicadaTheme.font(size: 13))
                .foregroundStyle(CicadaTheme.danger)
            VStack(alignment: .leading, spacing: 2) {
                Text("Sleep cycle error")
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(text)
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer()
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity)
        .background(CicadaTheme.danger.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    // MARK: Cancelled banner

    /// The last cycle stopped early because of a `/sleep/cancel` request
    /// (as opposed to completing normally, or a cancel that arrived too
    /// late to matter — see `sleep_cycle._cycle_cancelled`). Informational
    /// tone, matching `Copy.cancelSleepExplainer`'s own promise: nothing
    /// was lost.
    private var cancelledBanner: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "xmark.circle")
                .font(CicadaTheme.font(size: 12))
                .foregroundStyle(CicadaTheme.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text("Cancelled")
                    .font(CicadaTheme.font(size: 11, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Stopped cleanly before any writes — nothing was lost.")
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer()
        }
        .padding(CicadaTheme.spacingSM)
        .frame(maxWidth: .infinity)
        .background(CicadaTheme.accent.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    // MARK: Cap banner

    /// "Episode cap reached" — informational, not a warning: the cap is a
    /// deliberate safety feature (spec: bound one cycle's wall-clock instead
    /// of an unbounded first run), and the remaining episodes are simply
    /// picked up next cycle, nothing lost.
    private func capBanner(processed: Int, queued: Int, cap: Int) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "tray.and.arrow.down")
                .font(CicadaTheme.font(size: 12))
                .foregroundStyle(CicadaTheme.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text("Episode cap reached (\(cap))")
                    .font(CicadaTheme.font(size: 11, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("\(processed) of \(queued) processed — the rest stay queued for the next cycle.")
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer()
        }
        .padding(CicadaTheme.spacingSM)
        .frame(maxWidth: .infinity)
        .background(CicadaTheme.accent.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    // MARK: Warning banner

    private func warningBanner(_ text: String) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "exclamationmark.triangle")
                .font(CicadaTheme.font(size: 12))
                .foregroundStyle(CicadaTheme.warning)
            VStack(alignment: .leading, spacing: 2) {
                Text("Completed with warnings")
                    .font(CicadaTheme.font(size: 11, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(text)
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer()
        }
        .padding(CicadaTheme.spacingSM)
        .frame(maxWidth: .infinity)
        .background(CicadaTheme.warning.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }
}
