import Foundation

/// Everything the Sleep page draws, resolved ONCE per body evaluation (Track Z
/// §9, Z1).
///
/// The H1 rule — the room, the queue and the controls must never disagree
/// about which reading they show — used to be kept by hand: `SleepView`
/// resolved the SSE-vs-REST precedence in three computed properties and
/// evaluated `studyRows` twice per body. A value computed once makes the rule
/// structural, and it is pure, so every row of the design's data table is a
/// unit test instead of a screenshot.
///
/// Stored names never shadow the global functions they come from
/// (`scheduleText` ← `scheduleSentence`, `nextRunText` ← `nextRunSentence`,
/// `runningStage` ← `activeStage`) — Z-P2: an instance member with a
/// function's name makes the unqualified call inside `resolve` a compile error.
struct SleepPageModel: Equatable {
    var mood: BookwormState
    var debt: SleepDebtView?
    var isRunning: Bool
    /// The ACTIVE stage (R-Z14) while running; `nil` idle.
    var runningStage: Int?
    /// Sums of `resolveOriginCounts` — `Read a of b`, the strip's Read fill.
    var read: Int
    var total: Int
    var rows: [StudyRow]
    var books: [BookSpec]
    var pips: [StagePip]
    var schedule: ScheduleConfig
    /// R-A3 — the lamp and the schedule sentence read the same field.
    var lampLit: Bool
    var scheduleText: String
    var nextRunAt: String?
    var nextRunText: String
    /// `preview.manual.engine` — what the one control would run on; `nil`
    /// until loaded, never guessed.
    var manualEngine: String?
    /// "Scheduled runs use …" only when it differs from the manual engine
    /// (ruling 4, shown rather than applied).
    var scheduledEngineNote: String?
    /// The scheduled engine's id, under the same condition as
    /// `scheduledEngineNote`. It is kept as an id so every line that names
    /// the engine can draw its mark (Z-P26).
    var scheduledEngine: String?
    var queuedCount: Int
    var consolidateEnabled: Bool
    /// `status.error`, `nil` when empty — the failure is news, an empty string is not.
    var cycleError: String?
    var cancelled: Bool
    var capped: Bool
    var indexWarning: String?
    var queueLoad: StudyListCard.LoadState
    /// Z-P3 — the newest `kind == "sleep"` commit.
    var lastCycle: SleepHistoryEntry?
    var inboxTotal: Int?
    var oldestWait: String?
    var topOriginLabel: String?
    /// The top row's origin id: T12 names `topOriginLabel` and draws this
    /// origin's mark.
    var topOrigin: String?
    /// Task 6 — what the answer ladder names: the engine the last (or
    /// running) cycle used and the backend's own sentence about it, and the
    /// just-finished cycle's counts for the `.digesting` rung.
    var lastEngine: String?
    var engineDetail: String?
    var cycleCreated: Int
    var cycleUpdated: Int

    static func resolve(
        status: SleepStatusResponse?,
        sse: SleepEventPayload?,
        queued: [EpisodeQueueItem],
        schedule: ScheduleConfig,
        enginePreview: SleepEnginePreviews?,
        history: [SleepHistoryEntry],
        storeStatus: StatusSnapshot?,
        queueLoad: StudyListCard.LoadState,
        justFinishedAt: Date?,
        intakeInFlight: Bool,
        now: Date = .now,
        locale: Locale = .current,
        timeZone: TimeZone = .current
    ) -> SleepPageModel {
        let debt = resolveSleepDebt(sse: sse, status: status)
        let mood = deriveSleepPageMood(status: status, debt: debt, justFinishedAt: justFinishedAt,
                                       intakeInFlight: intakeInFlight, now: now)
        let origins = resolveOriginCounts(sse: sse, status: status)
        let isRunning = status?.status == "running"
        let read = origins.readByOrigin.values.reduce(0, +)
        let total = origins.queueByOrigin.values.reduce(0, +)
        let rows = studyRows(queued: queued, queueByOrigin: origins.queueByOrigin,
                             readByOrigin: origins.readByOrigin, running: isRunning, now: now)
        let error = status?.error.flatMap { $0.isEmpty ? nil : $0 }
        let cancelled = status?.cancelled == true
        let nextSleepAt = storeStatus?.nextSleepAt
        return SleepPageModel(
            mood: mood,
            debt: debt,
            isRunning: isRunning,
            runningStage: isRunning ? activeStage(completed: status?.stage ?? 0) : nil,
            read: read,
            total: total,
            rows: rows,
            books: bookPileLayout(originVolumes(queued: queued, queueByOrigin: origins.queueByOrigin,
                                                readByOrigin: origins.readByOrigin, running: isRunning)),
            pips: stageStripState(stage: status?.stage ?? 0, isRunning: isRunning, cancelled: cancelled,
                                  error: error != nil, read: read, total: total),
            schedule: schedule,
            lampLit: schedule.enabled,
            scheduleText: scheduleSentence(schedule),
            nextRunAt: nextRunWhen(schedule, nextSleepAt: nextSleepAt, locale: locale, timeZone: timeZone),
            nextRunText: nextRunSentence(schedule, nextSleepAt: nextSleepAt, locale: locale, timeZone: timeZone),
            manualEngine: enginePreview?.manual.engine,
            scheduledEngineNote: scheduledEngineLine(preview: enginePreview),
            scheduledEngine: enginePreview.flatMap { $0.manual.engine != $0.scheduled.engine ? $0.scheduled.engine : nil },
            queuedCount: queued.count,
            consolidateEnabled: status != nil && !isRunning && !queued.isEmpty,
            cycleError: error,
            cancelled: cancelled,
            capped: (status?.episodesQueued ?? 0) > (status?.episodesTotal ?? 0),
            indexWarning: status?.indexWarning.flatMap { $0.isEmpty ? nil : $0 },
            queueLoad: queueLoad,
            lastCycle: lastCycleEntry(history),
            inboxTotal: storeStatus?.inbox.total,
            oldestWait: oldestQueuedHours(queued, now: now).map(agePhrase(hours:)),
            topOriginLabel: rows.first?.label,
            topOrigin: rows.first?.origin,
            lastEngine: status?.lastEngine,
            engineDetail: status?.engineDetail,
            cycleCreated: status?.entitiesCreated ?? 0,
            cycleUpdated: status?.entitiesUpdated ?? 0
        )
    }
}

/// The newest real consolidation in `history` (Z-P3). `/sleep/history` also
/// lists the G85 `(decay)` commit and inbox-resolution commits; neither is a
/// cycle, and "See what changed ›" must never open the person's own inbox
/// answer as if Sleep had written it.
func lastCycleEntry(_ history: [SleepHistoryEntry]) -> SleepHistoryEntry? {
    history.first { $0.kind == "sleep" }
}

/// I17 vs I18 — the one running → idle edge that earns a cheer: not a cancel
/// (it filed nothing) and not a failure (that is news, told in danger). A
/// first observation (`old == nil`) is a page load, not an edge.
func isRealCompletion(old: String?, new: String?, cancelled: Bool, error: String?) -> Bool {
    old == "running" && new == "idle" && !cancelled && (error ?? "").isEmpty
}

/// The commit a completion produced, once history has it: the newest sleep
/// commit that was not the newest before the cycle finished (Z-P17). `nil`
/// while history has not caught up. It goes through `lastCycleEntry`, so the
/// G85 decay commit and an inbox answer landing in the same poll can never be
/// mistaken for what the cycle wrote (Z-P3).
func completedCommit(baseline: String?, history: [SleepHistoryEntry]) -> String? {
    guard let newest = lastCycleEntry(history)?.commitHash, newest != baseline else { return nil }
    return newest
}

extension SleepPageModel {
    /// The sentence's and the answers' inputs (Track Z §5, §6.3), from this
    /// one reading — so the status line and every rung the worm answers with
    /// can never read two different snapshots (H1).
    ///
    /// `recentCycleCommit` is the one input that is not a reading: it is the
    /// room's own memory of a completion it watched (Task 8, `RoomModel`), so
    /// the page passes it in rather than the model resolving it.
    func roomContext(recentCycleCommit: String? = nil, locale: Locale = .autoupdatingCurrent) -> RoomContext {
        var context = RoomContext(mood: mood, debt: debt, queueLoad: queueLoad, activeStage: runningStage,
                                  read: read, total: total, cycleError: cycleError, cancelled: cancelled,
                                  capped: capped, indexWarning: indexWarning, scheduleMode: schedule.mode,
                                  topOriginLabel: topOriginLabel, topOrigin: topOrigin, locale: locale)
        context.oldestWait = oldestWait
        context.lampLit = lampLit
        // After-import has no clock time until an import lands, but it does
        // have a when — words, not a dash (R-A14).
        context.nextRunWhen = nextRunAt ?? (schedule.mode == "after_import" ? "after the next import settles" : nil)
        context.scheduledEngine = scheduledEngine
        context.lastCycle = lastCycle.map { LastCycleFacts($0) }
        context.cycleCreated = cycleCreated
        context.cycleUpdated = cycleUpdated
        context.lastEngine = lastEngine
        context.engineDetail = engineDetail
        context.inboxTotal = inboxTotal
        context.recentCycleCommit = recentCycleCommit
        return context
    }
}
