import SwiftUI

// MARK: - Details for a run that reads in batches (Sleep page v5, A7)

extension LastCycleRow {
    /// Sleep page v5 — the run's own rows in Last cycle, in ruling 12's grammar: the run (in progress, finished or
    /// stopped) with its measured counts and times, a pause and why, the owner page's beliefs, what it made, the
    /// parked conversations with Retry, and — for a scheduled run on a metered engine — that Cicada set no limit.
    /// Pure, so `SleepV5DetailsTests` holds every row. A figure that was not measured is left out, never guessed.
    static func runRows(drain: SleepDrainInfo?, paused: SleepPausedRun?, run: SleepRunRef?, detail: SleepRunDetail?,
                        parkedCount: Int, scheduledBilling: String?, reserveValue: String?,
                        locale: Locale = .autoupdatingCurrent) -> [LastCycleRow] {
        var rows: [LastCycleRow] = []
        if let drain, drain.byOrigin != nil || drain.batchState != nil {
            let pauses = detail?.pauses.count ?? run?.pauses ?? 0
            if drain.active {
                rows.append(LastCycleRow(kind: .run, title: Copy.SleepV5.runLiveTitle,
                                         text: Copy.SleepV5.runLiveText(filed: drain.filed, frozen: drain.frozen,
                                                                        batches: drain.committedBatches ?? 0,
                                                                        calls: drain.calls, locale)))
            } else if drain.finished || paused != nil || drain.stop != nil {
                let readMs = detail?.readMs ?? run?.readMs
                let pausedMs = detail?.pausedMs ?? run?.pausedMs
                rows.append(LastCycleRow(
                    kind: .run,
                    title: drain.finished ? Copy.SleepV5.runDoneTitle
                        : (paused != nil ? Copy.SleepV5.runLiveTitle : Copy.SleepV5.runStoppedTitle),
                    text: Copy.SleepV5.runDoneText(filed: drain.filed, frozen: drain.frozen,
                                                   batches: drain.committedBatches ?? run?.batches ?? 0, pauses: pauses,
                                                   readFor: readMs.flatMap { $0 > 0 ? SleepHistoryPresentation.durationText(ms: $0) : nil },
                                                   pausedFor: pausedMs.flatMap { $0 > 0 ? SleepHistoryPresentation.durationText(ms: $0) : nil },
                                                   locale)))
            }
            if drain.startedBy == "schedule", let note = Copy.SleepV5.scheduledRunNote(scheduledBilling) {
                rows.append(LastCycleRow(kind: .scheduled, title: Copy.SleepV5.runLiveTitle, text: note))
            }
            if let owner = drain.ownerPage ?? detail?.owner {
                rows.append(LastCycleRow(kind: .owner, title: Copy.SleepV5.ownerBeliefsTitle(owner.beliefs, locale),
                                         text: Copy.SleepV5.ownerBeliefsText(atStart: owner.atStart,
                                                                             afterFirstBatch: owner.afterFirstBatch,
                                                                             firstBatch: drain.batchSize, locale) ?? ""))
            }
        }
        if let paused {
            let text: String
            switch paused.reason {
            case "reserve":
                text = drain.map { Copy.SleepV5.pausedReserveText(batch: max(1, $0.batch), locale) }
                    ?? Copy.SleepV5.pausedText(filed: paused.filed, frozen: paused.frozen, locale)
            case "engine":
                text = drain?.stop?.sentence ?? paused.sentence
                    ?? Copy.SleepV5.pausedText(filed: paused.filed, frozen: paused.frozen, locale)
            case "plan_window", "plan_weekly", "overage":
                text = paused.sentence ?? Copy.SleepV5.pausedText(filed: paused.filed, frozen: paused.frozen, locale)
            default:
                text = Copy.SleepV5.pausedText(filed: paused.filed, frozen: paused.frozen, locale)
            }
            rows.append(LastCycleRow(kind: .paused, title: Copy.SleepV5.pausedTitle(paused.reason), text: text))
            if paused.reason == "reserve", let reserveValue {
                rows.append(LastCycleRow(kind: .reserve, title: Copy.SleepV5.keepPlanFree,
                                         text: Copy.SleepV5.keepPlanFreeIs(reserveValue)))
            }
        }
        if let detail, detail.state == "finished" {
            if let created = detail.pages?.created, created > 0 {
                rows.append(LastCycleRow(kind: .pages, title: Copy.SleepV5.newPages(created, locale),
                                         text: Copy.SleepV5.pagesSummary(created: created,
                                                                         ownerTouched: detail.pages?.ownerTouched, locale)))
            }
            if let asked = detail.questionsRaised, asked > 0 {
                rows.append(LastCycleRow(kind: .questions, title: Copy.SleepV5.questionsForYou(asked, locale), text: ""))
            }
        }
        if parkedCount > 0 {
            rows.append(LastCycleRow(kind: .parked, title: Copy.SleepV5.parkedTitle,
                                     text: Copy.SleepV5.parkedText(parkedCount, locale)))
        }
        return rows
    }
}

/// One conversation in What's waiting while a run reads (A7): its title as the backend serves it, its day, and
/// where it stands in words — a failure beside a glyph, a parked one with Retry.
struct QueueItemRow: View {
    let item: SleepQueueItem
    var onRetry: (() -> Void)? = nil

    private var needsYou: Bool { item.state == "parked" || item.state == "could_not_be_read" }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Group {
                switch item.state {
                case "reading": ProgressView().controlSize(.mini)
                case "parked", "could_not_be_read":
                    Image(systemName: "exclamationmark.triangle").foregroundStyle(CicadaTheme.warning)
                case "read", "filed": Image(systemName: "checkmark").foregroundStyle(CicadaTheme.textTertiary)
                default: Image(systemName: "circle").foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .font(CicadaTheme.icon(.inline))
            .frame(width: CicadaTheme.scaled(14))
            .accessibilityHidden(true)
            Text(item.title ?? Copy.SleepDetailsWords.untitled)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
            Text(Copy.SleepV5.queueStateWords(state: item.state, reason: item.reason, attempts: item.attempts))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: 0)
            if item.state == "parked", let onRetry {
                NeutralButton(title: Copy.SleepV5.retry, size: .compact, action: onRetry)
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
            .fill(needsYou && item.state == "parked" ? CicadaTheme.bgHover : Color.clear))
        .help(item.id)
        .accessibilityElement(children: .combine)
    }
}
