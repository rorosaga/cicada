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
            topOrigin: rows.first?.origin
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
