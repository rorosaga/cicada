import SwiftUI

// MARK: - Pure state for one queue row (G125 v3 Task 6)

/// What a queue row draws, as a value — so the four cases and, crucially,
/// their PRECEDENCE are unit-testable without standing up a view.
///
/// `nextCycle` outranks `done`, and that ordering is the whole reason this is
/// a function rather than three `if`s in a `ViewBuilder`: a source the episode
/// cap left out of this cycle arrives as `total == 0` (`studyRows`'s own doc
/// comment), which is also `read == total`. Checked the other way round, a
/// source nothing has touched would render the finished ✓ — the exact
/// inversion of the truth.
enum QueueRowState: Equatable {
    /// Idle: the plain pile. There is nothing honest to count down when no
    /// cycle has claimed this source's episodes yet (R3).
    case waiting(Int)
    /// Running: `read of total`, with `fill` for the 3 pt micro-bar drawn
    /// behind the numbers. `fill` is derived here so the bar and the words can
    /// never disagree (the same one-reading rule the hero meter follows, P7).
    case reading(read: Int, total: Int, fill: Double)
    /// This source is fully read — a dimmed ✓, no numbers. The cycle moved on
    /// to stages the strip reports; repeating `188 / 188` would be noise.
    case done
    /// In the queue but left out of THIS cycle by the episode cap.
    case nextCycle
}

func queueRowState(_ row: StudyRow) -> QueueRowState {
    guard let read = row.read, let total = row.total else { return .waiting(row.count) }
    if total == 0 { return .nextCycle }
    if read >= total { return .done }
    return .reading(read: read, total: total, fill: Double(read) / Double(total))
}

// MARK: - The schedule sentence (P11 / R-A3)

/// The desk lamp is lit iff `mode != "manual"`. **Art never carries a fact
/// alone** — this is the lamp's mandatory text twin, and it is a pure function
/// of `ScheduleConfig` so the two can be read against each other in a test.
///
/// It never invents a time it was not given: an unrecognized mode from a newer
/// backend reads as "manual only" rather than as a schedule nobody configured.
func scheduleSentence(_ schedule: ScheduleConfig) -> String {
    switch schedule.mode {
    case "daily":
        return String(format: "Every day at %02d:%02d", schedule.hour, schedule.minute)
    case "interval":
        return schedule.intervalHours == 1 ? "Every hour" : "Every \(schedule.intervalHours) h"
    case "after_import":
        return "After imports settle"
    default:
        return Copy.nextRunManual
    }
}

/// The footer's second line — present **only** when the manual and scheduled
/// previews name different engines (R-A9).
///
/// The standing ruling (a scheduled cycle never spends plan quota) makes those
/// two genuinely different on a plan-backed bank. Showing the line only on a
/// difference is the point: an asymmetry the reader can see is a decision,
/// one applied silently is a surprise. A missing preview yields `nil` — an
/// unloaded fact is never guessed at.
func scheduledEngineLine(preview: SleepEnginePreviews?) -> String? {
    guard let preview, preview.manual.engine != preview.scheduled.engine else { return nil }
    return Copy.scheduledRunsOn(engine: preview.scheduled.engine)
}

/// "What is waiting for the next cycle", grouped by source (G125 — replaces
/// the old `SleepQueueCard` + `SleepDebtBreakdown` pair, R1/R11). One row per
/// origin, largest pile first; a chevron discloses that origin's episodes
/// inline. The one Consolidate/Cancel control lives in the hero since G125 v3
/// (R-A7) — the ruling is still "exactly one on this page", only its home
/// moved — which leaves this card saying, top to bottom, exactly one thing:
/// **what is waiting, and when it will be read.** Under the rows sits the
/// schedule row (the desk lamp's mandatory text twin, P11/R-A3) and then the
/// footer: the next run, and the engine a *scheduled* run would use whenever
/// that differs from a manual one.
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
            Text("IN THE QUEUE")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            content

            Divider().background(CicadaTheme.border).padding(.vertical, CicadaTheme.spacingXS)

            scheduleRow

            // R-A7 (upgrading G125 R10): the one Consolidate/Cancel control
            // moved to the hero, where the decision is actually made — the
            // count, the meter and the engine it would run on are all right
            // there. This footer keeps only the lines that say WHEN the next
            // run happens, and on what, without anyone clicking anything.
            footer

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
        .accessibilityLabel(Self.rowAccessibilityLabel(row))
    }

    /// The trailing mark's meaning in words — the ✓ and the micro-fill are
    /// both silent to VoiceOver, so the state has to arrive here instead.
    static func rowAccessibilityLabel(_ row: StudyRow) -> String {
        switch queueRowState(row) {
        case .waiting(let count): return "\(row.label), \(count) queued"
        case .reading(let read, let total, _): return "\(row.label), \(read) of \(total) read"
        case .done: return "\(row.label), fully read"
        case .nextCycle: return "\(row.label), waiting for the next cycle"
        }
    }

    /// Renders `queueRowState`, which owns the precedence (see its doc
    /// comment). The running row lost its 60 pt `ProgressView`: a spinner-
    /// shaped control beside a real `12 / 188` says nothing the numbers do not
    /// already say, and at eight rows it was eight competing bars. What
    /// replaces it is a 3 pt micro-fill drawn *behind* the count — the same
    /// fraction, at a weight that reads as a texture on the number rather than
    /// as a second widget.
    @ViewBuilder
    private func trailing(_ row: StudyRow) -> some View {
        switch queueRowState(row) {
        case .nextCycle:
            Text("next cycle")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        case .done:
            // Dimmed, and no numbers: this source is finished, and the cycle's
            // live readout has moved on to the stage strip.
            Image(systemName: "checkmark")
                .font(CicadaTheme.font(size: 10, weight: .semibold))
                .foregroundStyle(CicadaTheme.textTertiary)
        case .waiting(let count):
            countText("\(count)")
        case .reading(let read, let total, let fill):
            countText("\(read) / \(total)")
                .background(alignment: .bottom) { microFill(fill) }
        }
    }

    private func countText(_ value: String) -> some View {
        Text(value)
            .font(CicadaTheme.font(size: 12, weight: .semibold, design: .rounded))
            .foregroundStyle(CicadaTheme.textSecondary)
    }

    /// 3 pt tall, as wide as the count it sits under. Decorative in the
    /// accessibility sense only — the numbers above it carry the same fact,
    /// which is why it can be hidden from VoiceOver without losing anything.
    private func microFill(_ fraction: Double) -> some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(CicadaTheme.border)
                Capsule()
                    .fill(CicadaTheme.accent)
                    .frame(width: geo.size.width * min(max(fraction, 0), 1))
            }
        }
        .frame(height: 3)
        .padding(.bottom, -1)
        .accessibilityHidden(true)
    }

    // MARK: The schedule row — the lamp's text twin (P11 / R-A3)

    /// The desk scene's lamp is lit exactly when Sleep is scheduled. **No art
    /// bit on this page carries a fact alone**, so the same state is stated
    /// here in words, with the one link that opens where it is changed.
    private var scheduleRow: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "moon.zzz")
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text(scheduleSentence(sleepVM.schedule))
                .font(CicadaTheme.font(size: 12, weight: .medium))
                .foregroundStyle(CicadaTheme.textSecondary)
            SettingsSectionLink(section: .sleep, label: Copy.changeEllipsis)
                .font(CicadaTheme.captionFont)
            Spacer(minLength: 0)
        }
    }

    /// `nextRunText`, plus the scheduled engine ONLY when it differs from what
    /// a manual run would use (R-A9) — the standing quota ruling made visible
    /// rather than applied behind the reader's back.
    private var footer: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(nextRunText)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            if let line = scheduledEngineLine(preview: sleepVM.enginePreview) {
                Text(line)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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

    /// "Manual only" / "Next run …" / "… after the next import". The pointer
    /// to Settings → Sleep moved up to `scheduleRow`, where the sentence it
    /// would change is: two links to one destination, eighteen points apart,
    /// is a choice the reader should not have to make.
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
