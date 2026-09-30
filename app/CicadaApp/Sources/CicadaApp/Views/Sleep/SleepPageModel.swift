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
    /// G163 — the person-started run's measured progress, `nil` when the last cycle was not one.
    var drain: SleepDrainInfo?
    /// `cancelled`, or a finished run that stopped at a plan limit: the strip freezes and nothing cheers.
    var stoppedEarly: Bool
    /// The plan pause's reset time has passed (`SleepDrainInfo.Stop.planPauseLapsed`): its tail and row retire.
    var planPauseLapsed: Bool
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

    // MARK: Sleep page v5 (G163; rulings 13, 15, 16)

    /// The paused run (Pause, a plan limit, the reserve, the engine, a restart) — `nil` while reading or when
    /// nothing is paused. A paused run is `idle`: it holds nothing, and only this page's Continue resumes it.
    var paused: SleepPausedRun? = nil
    /// How often a run saves (Reading options, else the configured batch size).
    var batchSize: Int = 25
    /// What a Consolidate would read now (waiting minus parked, M7).
    var readable: Int? = nil
    /// Conversations parked after failing twice for their own reasons.
    var parkedCount: Int = 0
    /// The paused run's reset time in words ("after 3:40 PM", "Tue 2:00 PM") — one locale-aware formatter (L2),
    /// resolved here so the sentence stays clock-free.
    var resetWhen: String? = nil
    /// When an armed automatic continue fires, in the same words; `nil` unless armed (ruling 15).
    var autoContinueWhen: String? = nil
    /// Continue cannot help yet: a weekly plan limit whose reset is still ahead (the board's disabled Continue).
    var continueWaitsForReset: Bool = false
    /// The Pause was asked for and the run has not stopped yet.
    var pausing: Bool = false

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
        paused: SleepPausedRun? = nil,
        batchSize: Int? = nil,
        pausing: Bool = false,
        now: Date = .now,
        locale: Locale = .current,
        timeZone: TimeZone = .current
    ) -> SleepPageModel {
        let debt = resolveSleepDebt(sse: sse, status: status)
        let isPaused = paused != nil && status?.status != "running"
        let mood = deriveSleepPageMood(status: status, debt: debt, justFinishedAt: justFinishedAt,
                                       intakeInFlight: intakeInFlight, paused: isPaused, now: now)
        let origins = resolveOriginCounts(sse: sse, status: status)
        let isRunning = status?.status == "running"
        let read = origins.readByOrigin.values.reduce(0, +)
        let total = origins.queueByOrigin.values.reduce(0, +)
        let rows = studyRows(queued: queued, queueByOrigin: origins.queueByOrigin,
                             readByOrigin: origins.readByOrigin, running: isRunning, now: now)
        let error = status?.error.flatMap { $0.isEmpty ? nil : $0 }
        let cancelled = status?.cancelled == true
        let drain = resolveDrain(sse: sse, status: status)
        // A run that ended early on purpose or by a limit: the strip freezes where it stopped and nothing
        // cheers. A cancel already says so; a plan limit is the same in every way but the flag (G163).
        // The backend keeps `drain.stop` until the next run, so a stop cannot hold the strip forever: a cancel
        // follows `cancelled` (the backend's own five-minute window), and a plan pause ends at its reset time.
        let planPauseLapsed = drain?.stop?.planPauseLapsed(now: now) ?? false
        let stoppedEarly = cancelled || (!isRunning && drain?.stop.map {
            $0.reason != "cancelled" && !($0.reason == "plan_limit" && planPauseLapsed) } == true)
        let nextSleepAt = storeStatus?.nextSleepAt
        let shownPause = isPaused ? paused : nil
        let resetDate = shownPause?.resetsAt.map { Date(timeIntervalSince1970: TimeInterval($0)) }
        let autoAt = shownPause?.autoContinue.flatMap { $0.armed ? $0.at : nil }
            .map { Date(timeIntervalSince1970: TimeInterval($0)) }
        let parked = sse?.parkedCount ?? status?.debt.parkedCount ?? 0
        let readable = sse?.readableCount ?? status?.debt.readableCount ?? status.map { $0.debt.readable }
        var model = SleepPageModel(
            mood: mood,
            debt: debt,
            isRunning: isRunning,
            runningStage: isRunning ? activeStage(completed: status?.stage ?? 0) : nil,
            read: read,
            total: total,
            rows: rows,
            books: bookPileLayout(originVolumes(queued: queued, queueByOrigin: origins.queueByOrigin,
                                                readByOrigin: origins.readByOrigin, running: isRunning)),
            pips: stageStripState(stage: status?.stage ?? 0, isRunning: isRunning, cancelled: stoppedEarly,
                                  error: error != nil,
                                  read: drain.flatMap { $0.active ? $0.batchState?.read : nil } ?? read,
                                  total: drain.flatMap { $0.active ? $0.batchState?.total : nil } ?? total,
                                  stages: drain?.stages),
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
            // A drain reads everything it froze; "queued > attempted" means "not yet" there, never "capped".
            capped: drain == nil && (status?.episodesQueued ?? 0) > (status?.episodesTotal ?? 0),
            drain: drain,
            stoppedEarly: stoppedEarly,
            planPauseLapsed: planPauseLapsed,
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
        model.paused = shownPause
        model.batchSize = batchSize ?? (status.map { $0.batchSize > 0 ? $0.batchSize : 25 } ?? 25)
        model.readable = readable
        model.parkedCount = parked
        model.resetWhen = resetDate.map { sleepClockWords($0, now: now, locale: locale, timeZone: timeZone, afterToday: true) }
        model.autoContinueWhen = autoAt.map { sleepClockWords($0, now: now, locale: locale, timeZone: timeZone, afterToday: false) }
        model.continueWaitsForReset = shownPause?.reason == "plan_weekly" && (resetDate.map { $0 > now } ?? false)
        model.pausing = pausing && isRunning
        // A paused run is continued, not consolidated afresh: the one primary is Continue (A4, DR-40).
        if shownPause != nil { model.consolidateEnabled = false }
        return model
    }
}

/// One locale-aware way to say a reset or a continue time (L2): today reads "after 3:40 PM" (or "3:40 PM" when the
/// sentence already says "after"), another day "Tue 2:00 PM". Pure: the page passes its own `now`, locale and zone.
func sleepClockWords(_ date: Date, now: Date, locale: Locale, timeZone: TimeZone, afterToday: Bool) -> String {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = timeZone
    let f = DateFormatter()
    f.locale = locale
    f.timeZone = timeZone
    if calendar.isDate(date, inSameDayAs: now) {
        f.setLocalizedDateFormatFromTemplate("jmm")
        return afterToday ? "after \(f.string(from: date))" : f.string(from: date)
    }
    f.setLocalizedDateFormatFromTemplate("EEEjmm")
    return f.string(from: date)
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
func isRealCompletion(old: String?, new: String?, cancelled: Bool, error: String?,
                      drainStop: String? = nil) -> Bool {
    old == "running" && new == "idle" && !cancelled && (error ?? "").isEmpty && drainStop == nil
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
                                  capped: capped, drain: drain, planPauseLapsed: planPauseLapsed, indexWarning: indexWarning, scheduleMode: schedule.mode,
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
        context.paused = paused
        context.batchSize = batchSize
        context.resetWhen = resetWhen
        context.autoContinueWhen = autoContinueWhen
        context.pausing = pausing
        return context
    }
}
