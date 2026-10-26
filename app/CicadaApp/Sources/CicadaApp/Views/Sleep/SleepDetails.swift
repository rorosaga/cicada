import SwiftUI

/// Whether Past reads › Last cycle has anything to say (Track Z §4.1 F). The
/// four inputs are exactly the four banners' own conditions, so the section
/// can never render as an empty header.
func lastCycleSectionIsVisible(pageError: String?, cancelled: Bool, capped: Bool, indexWarning: String?,
                               usageLine: String? = nil, drain: SleepDrainInfo? = nil) -> Bool {
    pageError != nil || cancelled || capped || !(indexWarning ?? "").isEmpty || usageLine != nil
        || LastCycleRow.drainHasNews(drain)
}

/// The Sleep redesign (owner approval 2026-10-16, DESIGN §3.4) — Details retired, and its four sections became two of
/// the page's tabs: **Waiting** (this view: the run's own block, then the queued conversations, parked ones at their
/// foot with Retry) and **Past reads** (`SleepPastReads`). Each is built only while its tab is selected, so an unseen
/// list costs nothing (design §10's budget, which the closed disclosure used to keep).
///
/// R-A12: the lists take the liveness desaturation; news (Past reads' Last cycle) never does. The `.saturation` is
/// applied unconditionally (identity 1.0 while live): a conditional modifier would remount the list and empty
/// `StudyListCard`'s expanded rows whenever the connection flaps.
struct SleepWaitingList: View {
    let page: SleepPageModel
    let liveness: SleepLiveness
    let episodes: [EpisodeQueueItem]
    /// G212 — one machine's queue open: its rows, built from its own episodes (nil: the page's rows, every machine's).
    var machineRows: [StudyRow]? = nil
    var onSelectEntity: ((String) -> Void)?
    /// Track Z Z6 (I5, I7) — hands the room to the rows, so a row and its spine answer each other's hover.
    var room: RoomModel? = nil
    /// Sleep page v5 (A7) — the run's per-conversation queue, and the callbacks for Retry and the person's own page.
    var queue: SleepQueueResponse? = nil
    var showsRun: Bool = false
    /// Whether a run waits paused per the live event, even before its record has loaded (`SleepViewModel.isPaused`).
    var runPaused: Bool = false
    var ownerReady: Bool = false
    var onRetryParked: ([String]?) -> Void = { _ in }
    var onSeeOwnerPage: (() -> Void)? = nil

    /// Retry on a parked conversation only when the server would take it: no run reading, none waiting paused.
    private var canRetry: Bool {
        LastCycleRow.canRetryParked(isRunning: page.isRunning, isPaused: runPaused || page.paused != nil)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingCard) {
            if showsRun || ownerReady {
                RunWaitingBlock(drain: page.drain, queue: queue, showsRun: showsRun, ownerReady: ownerReady,
                                onRetry: canRetry ? onRetryParked : nil, onSeeOwnerPage: onSeeOwnerPage)
                    .saturation(liveness.saturation)
            }
            StudyListCard(rows: machineRows ?? page.rows, episodes: episodes, queueLoad: page.queueLoad,
                          onSelectEntity: onSelectEntity, room: room)
                .id(DetailsSection.waiting.anchorID)
                .saturation(liveness.saturation)
        }
    }
}

/// Past reads (DESIGN §3.4): Last cycle first — the run's own rows, at full contrast (R-A12) — then the Readout's
/// key–value rows, then Past nights, one row per run or cycle. Opening a row shows that read in place: what it read,
/// the pages it touched, Models with tokens and cost and their basis (ruling 12 — prices and plan usage show on this
/// page only here, and in the engine menu).
struct SleepPastReads: View {
    let page: SleepPageModel
    let liveness: SleepLiveness
    let pageError: String?
    let status: SleepStatusResponse?
    let history: [SleepHistoryEntry]
    let details: [String: SleepCycleDetail]
    let expanded: String?
    let onToggleHistory: (String) -> Void
    var onSelectEntity: ((String) -> Void)?
    /// Sleep page v5 (A7) — the run's own Last cycle rows (`LastCycleRow.runRows`).
    var runRows: [LastCycleRow] = []
    var runPaused: Bool = false
    var onRetryParked: ([String]?) -> Void = { _ in }
    var runDetails: [String: SleepRunDetail] = [:]
    var expandedRun: String? = nil
    var onToggleRun: (String) -> Void = { _ in }
    /// The run cards' dropdowns (owner 2026-10-26): what each consolidation read and wrote, and the loader an open asks.
    var items: [SleepConsolidatedKey: SleepConsolidated] = [:]
    var itemsFailed: Set<SleepConsolidatedKey> = []
    var onLoadItems: (SleepConsolidatedKey) -> Void = { _ in }

    /// Retry on a parked conversation only when the server would take it: no run reading, none waiting paused.
    private var canRetry: Bool {
        LastCycleRow.canRetryParked(isRunning: page.isRunning, isPaused: runPaused || page.paused != nil)
    }

    /// The latest finished cycle's three figures — time, engine, cost — from one history record.
    private var lastFigures: LastCycleFigures? { LastCycleFigures.resolve(status: status, history: history) }

    /// The latest finished cycle's one-line cost, only when one was recorded — "not recorded" belongs to Past
    /// nights, where every row can say it, and never opens this section by itself.
    private var lastCycleUsage: String? {
        CycleUsageText.lastCycleLine(lastFigures?.usage)
    }

    var body: some View {
        // R-HS15 — 28 pt between sections, the D-Sleep mock's gap: sections are labels over rows, so the space
        // between them is what separates them (DR-37).
        VStack(alignment: .leading, spacing: CicadaTheme.spacingCard) {
            if lastCycleSectionIsVisible(pageError: pageError, cancelled: page.cancelled,
                                         capped: page.capped, indexWarning: page.indexWarning,
                                         usageLine: lastCycleUsage, drain: page.drain) || !runRows.isEmpty {
                LastCycleSection(pageError: pageError, status: status, cancelled: page.cancelled,
                                 capped: page.capped, indexWarning: page.indexWarning, drain: page.drain,
                                 planPauseLapsed: page.planPauseLapsed, usageLine: lastCycleUsage,
                                 usageIsOneBatch: lastFigures?.isOneBatch ?? false,
                                 usageHelp: CycleUsageText.summaryHelp(lastFigures?.usage),
                                 runRows: runRows, onRetryParked: canRetry ? { onRetryParked(nil) } : nil)
                    .id(DetailsSection.lastCycle.anchorID)
            }
            SleepReadoutView(mood: page.mood, debt: page.debt, read: page.read, total: page.total,
                             lastDurationMs: lastFigures?.durationMs,
                             lastIsOneBatch: lastFigures?.isOneBatch ?? false,
                             lastEngine: lastFigures?.engine,
                             // The status's reason describes the engine the backend last resolved; it is shown only
                             // beside that same engine, never under another cycle's.
                             engineDetail: status?.lastEngine == lastFigures?.engine ? status?.engineDetail : nil,
                             hasFinishedCycle: lastFigures != nil,
                             engineShownBelow: lastFigures?.engine != nil
                                 && history.first(where: { $0.kind == "sleep" })?.engine == lastFigures?.engine)
                .id(DetailsSection.readout.anchorID)
                .saturation(liveness.saturation)
            ConsolidationHistoryCard(entries: history, details: details, expanded: expanded, expandedRun: expandedRun,
                                     runDetails: runDetails, items: items, itemsFailed: itemsFailed,
                                     onToggle: { card in
                                         switch card.key {
                                         case .run(let id): onToggleRun(id)
                                         case .commit(let hash): onToggleHistory(hash)
                                         }
                                         onLoadItems(card.key)
                                     },
                                     onSelectEntity: onSelectEntity, onLoadItems: onLoadItems)
                .id(DetailsSection.pastNights.anchorID)
                .saturation(liveness.saturation)
        }
    }
}

/// DR-20, DR-37, DR-47 — one section of a Sleep tab in D's list grammar (R-HS15; Details' until 2026-10-16): its `SectionLabel` over
/// rows, no card. Details was four glass cards with their labels inside; §10 (Sleep) asks for "rows
/// and section labels, no bordered cards".
struct SleepDetailsSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            // A tab that names its own list passes no title (the Waiting tab, 2026-10-16).
            if !title.isEmpty {
                SectionLabel(title)
                    .padding(.horizontal, CicadaTheme.scaled(10))
            }
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Past reads' three "last cycle" figures — how long it took, its engine, what it cost — read from ONE record (live
/// report, 2026-10-16: after a scheduled drain and then a plan drain, Details still showed one batch's charge and
/// time and a dash for the engine). The backend finds the newest FINISHED cycle (`status.lastFinishedCycle`): a drain
/// is one cycle — its run's reading time, the engine its commits name, the whole run's cost — and a run still reading
/// or paused is skipped however many history rows it fills. An older backend that does not send the field falls back
/// to the newest history row's own figures, titled as one batch when that row is a run's batch.
struct LastCycleFigures: Equatable {
    var durationMs: Int?
    var engine: String?
    var usage: CycleUsageSummary?
    var isOneBatch = false

    /// `nil` = no finished cycle to show (the backend said so, or, from an older backend, history has no cycle).
    static func resolve(status: SleepStatusResponse?, history: [SleepHistoryEntry]) -> LastCycleFigures? {
        if let status, status.reportsLastFinishedCycle {
            guard let c = status.lastFinishedCycle else { return nil }
            return LastCycleFigures(durationMs: c.durationMs, engine: c.engine ?? c.usageSummary?.engine,
                                    usage: c.usageSummary)
        }
        guard let entry = history.first(where: { $0.kind == "sleep" }) else { return nil }
        return LastCycleFigures(durationMs: entry.durationMs, engine: entry.engine ?? entry.usageSummary?.engine,
                                usage: entry.usageSummary, isOneBatch: entry.drainId != nil || (entry.batches ?? 0) > 1)
    }
}

/// One line of Past reads › Last cycle (R-HS15): what happened, in the words the banners said, and a
/// glyph that says whether it needs the person — a failure or a warning in `warning`, a cancel or a
/// cap in `textTertiary`. The filled banners (`danger`/`accent`/`warning` at 10–12 %) retired: DR-7
/// keeps `danger` for destructive actions, and a row never sits on a tint.
struct LastCycleRow: Equatable, Identifiable {
    enum Kind: String, Equatable {
        case failed, cancelled, capped, warning, usage, drain, paused
        // Sleep page v5 (A7).
        case run, scheduled, owner, reserve, pages, questions, parked
    }

    let kind: Kind
    let title: String
    let text: String
    var id: String { kind.rawValue }
    var needsYou: Bool { kind == .failed || kind == .warning || kind == .parked }
    var glyph: String {
        switch kind {
        case .failed, .warning, .parked: "exclamationmark.triangle"
        case .cancelled, .paused: "pause.circle"
        case .run: "books.vertical"
        case .scheduled: "clock"
        case .owner: "person.crop.circle"
        case .reserve: "gauge.with.dots.needle.33percent"
        case .pages: "doc.on.doc"
        case .questions: "tray"
        case .drain: "text.book.closed"
        case .capped: "tray.and.arrow.down"
        case .usage: "gauge.with.dots.needle.33percent"
        }
    }

    /// The four conditions `lastCycleSectionIsVisible` reads, in the page's order. The cap's numbers
    /// come from the status itself, as the banner's did (L1/L4).
    /// A finished person-started run is news only when it took more than one batch or something is still
    /// waiting — a plain one-batch read needs no row of its own (G163).
    static func drainHasNews(_ drain: SleepDrainInfo?) -> Bool {
        guard let drain, !drain.active else { return false }
        // A run that stopped is always news: how much stays filed. Only a run that finished may say "read
        // everything", and only when it took several batches or left something for next time.
        if drain.stop != nil { return true }
        return drain.finished && (drain.batches > 1 || drain.requeued > 0)
    }

    static func rows(pageError: String?, cancelled: Bool, capped: Bool, indexWarning: String?,
                     status: SleepStatusResponse?, usageLine: String? = nil, usageIsOneBatch: Bool = false,
                     drain: SleepDrainInfo? = nil, planPauseLapsed: Bool = false,
                     locale: Locale = .autoupdatingCurrent) -> [LastCycleRow] {
        var rows: [LastCycleRow] = []
        if let pageError {
            rows.append(LastCycleRow(kind: .failed, title: Copy.SleepDetailsWords.failedTitle, text: pageError))
        }
        if cancelled {
            // After a person-started run, "before any writes" and "nothing was lost" would be false: the batch
            // that was reading is dropped and its reads are paid again.
            let text = drain.map { $0.filed > 0
                ? Copy.SleepDetailsWords.cancelledDrainText(filed: $0.filed, frozen: $0.frozen, locale: locale)
                : Copy.SleepDetailsWords.cancelledDrainNoneText() }
                ?? Copy.SleepDetailsWords.cancelledText
            rows.append(LastCycleRow(kind: .cancelled, title: Copy.SleepDetailsWords.cancelledTitle, text: text))
        }
        // The vendor's own sentence, whole (it carries the reset time) — until that time has passed.
        if let drain, drain.stop?.reason == "plan_limit", !planPauseLapsed {
            rows.append(LastCycleRow(kind: .paused, title: Copy.SleepDetailsWords.pausedTitle,
                                     text: drain.stop?.sentence ?? Copy.SleepDetailsWords.pausedFallback))
        }
        if drainHasNews(drain), let drain {
            if let stop = drain.stop {
                // The cancel row already says how much stays filed while its window lasts; after it, this row
                // is what keeps saying the run stopped.
                if !(cancelled && stop.reason == "cancelled") {
                    let title = stop.reason == "cancelled" ? Copy.SleepDetailsWords.cancelledTitle
                        : Copy.SleepDetailsWords.stoppedTitle
                    rows.append(LastCycleRow(kind: .drain, title: title,
                                             text: Copy.SleepDetailsWords.stoppedText(filed: drain.filed, frozen: drain.frozen,
                                                                                      locale: locale)))
                }
            } else {
                rows.append(LastCycleRow(kind: .drain, title: Copy.SleepDetailsWords.drainTitle,
                                         text: Copy.SleepDetailsWords.drainText(filed: drain.filed, frozen: drain.frozen,
                                                                                 batches: drain.batches, requeued: drain.requeued,
                                                                                 locale: locale)))
            }
        }
        // A drain has no episode cap to report: it reads everything it froze, so "queued > attempted"
        // means it stopped, which the rows above say.
        if capped, drain == nil, let s = status {
            rows.append(LastCycleRow(kind: .capped, title: Copy.SleepDetailsWords.capTitle(s.episodeCap, locale: locale),
                                     text: Copy.SleepDetailsWords.capText(processed: s.episodesTotal,
                                                                          queued: s.episodesQueued, locale: locale)))
        }
        // Non-fatal warnings (e.g. the episode index rebuild failed even though entity writes and
        // the commit succeeded), so a "completed with warnings" cycle never looks like a clean pass.
        if let warning = indexWarning, !warning.isEmpty {
            rows.append(LastCycleRow(kind: .warning, title: Copy.SleepDetailsWords.warningTitle, text: warning))
        }
        // 2026-09-28 — what the newest cycle cost, last: it is information, not news that needs you.
        if let usageLine {
            // A drain's figure is the whole run's (`LastCycleFigures`); only a batch whose run summary is missing is
            // titled as one batch (ruling 12: a basis).
            let title = usageIsOneBatch ? Copy.SleepUsage.lastBatchTitle : Copy.SleepUsage.lastCycleTitle
            rows.append(LastCycleRow(kind: .usage, title: title, text: usageLine))
        }
        return rows
    }
}

/// Past reads › Last cycle — the error (`pageError`), the cancel, the episode cap and the index warning,
/// at full contrast (R-A12). Moved from `SleepView` (Track Z §4.2); R-HS15 turned its four filled
/// banners into `LastCycleRow`s under the section's label.
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
    var drain: SleepDrainInfo? = nil
    var planPauseLapsed: Bool = false
    var usageLine: String? = nil
    var usageIsOneBatch: Bool = false
    var usageHelp: String? = nil
    /// Sleep page v5 — the run's rows; they replace the pre-v5 drain and pause rows (`LastCycleRow.merged`).
    var runRows: [LastCycleRow] = []
    var onRetryParked: (() -> Void)? = nil

    var body: some View {
        SleepDetailsSection(title: "Last cycle") {
            ForEach(LastCycleRow.merged(legacy: LastCycleRow.rows(pageError: pageError, cancelled: cancelled,
                                                                  capped: capped, indexWarning: indexWarning,
                                                                  status: status, usageLine: usageLine,
                                                                  usageIsOneBatch: usageIsOneBatch, drain: drain,
                                                                  planPauseLapsed: planPauseLapsed),
                                        run: runRows)) { row in
                HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
                    Image(systemName: row.glyph)
                        .font(CicadaTheme.icon(.list))
                        .foregroundStyle(row.needsYou ? CicadaTheme.warning : CicadaTheme.textTertiary)
                        .padding(.top, CicadaTheme.scaled(2))
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                        Text(row.title)
                            .font(CicadaTheme.rowFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                        Text(row.text)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .help(row.kind == .usage ? (usageHelp ?? "") : "")
                    }
                    Spacer(minLength: 0)
                    if row.kind == .parked, let onRetryParked {
                        NeutralButton(title: Copy.SleepV5.retry, size: .compact, action: onRetryParked)
                    }
                }
                .padding(.horizontal, CicadaTheme.scaled(10))
                .padding(.vertical, CicadaTheme.spacingSM)
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(row.needsYou ? .isStaticText : [])
            }
        }
    }
}
