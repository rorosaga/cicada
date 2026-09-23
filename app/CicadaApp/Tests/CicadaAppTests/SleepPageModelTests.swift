import XCTest
@testable import CicadaApp

/// Track Z, Z1 — every number and state the Sleep page draws (design §9),
/// resolved once from fixtures. The SSE-over-REST precedence the Store has
/// always had is asserted here for the page as a whole, so a later task
/// cannot quietly read one half from SSE and the other from REST.
final class SleepPageModelTests: XCTestCase {

    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private let utc = TimeZone(identifier: "UTC")!
    private let posix = Locale(identifier: "en_US_POSIX")

    private func status(_ json: String) throws -> SleepStatusResponse {
        try JSONDecoder().decode(SleepStatusResponse.self, from: Data(json.utf8))
    }

    private func episode(_ id: String, _ origin: String, hoursAgo: Double, chars: Int = 100) throws -> EpisodeQueueItem {
        let stamp = ISO8601DateFormatter().string(from: now.addingTimeInterval(-hoursAgo * 3600))
        return try JSONDecoder().decode(EpisodeQueueItem.self, from: Data("""
        {"id":"\(id)","timestamp":"\(stamp)","source":"mcp","origin":"\(origin)","preview":"","chars":\(chars),"processed":false}
        """.utf8))
    }

    private func entry(_ hash: String, kind: String, episodes: Int = 3, durationMs: Int? = nil) throws -> SleepHistoryEntry {
        let duration = durationMs.map(String.init) ?? "null"
        return try JSONDecoder().decode(SleepHistoryEntry.self, from: Data("""
        {"commitHash":"\(hash)","date":"2026-09-20T03:00:00+00:00","message":"x","kind":"\(kind)",
         "episodes":\(episodes),"entitiesCreated":2,"entitiesUpdated":1,"durationMs":\(duration)}
        """.utf8))
    }

    private func snapshot(inbox: Int = 0, nextSleepAt: String? = nil) -> StatusSnapshot {
        StatusSnapshot(sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
                       inbox: .init(total: inbox, byKind: [:]),
                       episodes: .init(unprocessed: 0, lastIngestedAt: nil),
                       lastSleepAt: nil, nextSleepAt: nextSleepAt)
    }

    private func resolve(status: SleepStatusResponse?, sse: SleepEventPayload? = nil,
                         queued: [EpisodeQueueItem] = [], schedule: ScheduleConfig = ScheduleConfig(mode: "manual", hour: 3, minute: 0),
                         preview: SleepEnginePreviews? = nil, history: [SleepHistoryEntry] = [],
                         storeStatus: StatusSnapshot? = nil,
                         queueLoad: StudyListCard.LoadState = .loaded(count: 0),
                         justFinishedAt: Date? = nil, intakeInFlight: Bool = false) -> SleepPageModel {
        SleepPageModel.resolve(status: status, sse: sse, queued: queued, schedule: schedule,
                               enginePreview: preview, history: history, storeStatus: storeStatus,
                               queueLoad: queueLoad, justFinishedAt: justFinishedAt,
                               intakeInFlight: intakeInFlight, now: now, locale: posix, timeZone: utc)
    }

    private let idleJSON = #"{"status":"idle","debt":{"unprocessedCount":2,"oldestUnprocessedAgeHours":null,"hoursSinceLastCycle":5,"hasRunBefore":true,"volumePct":10,"agePct":10,"restedPct":80}}"#

    func test_mood_andTheRunningStageComeFromTheOneDerivation() throws {
        let running = resolve(status: try status(#"{"status":"running","stage":1}"#))
        XCTAssertEqual(running.mood, .sleeping(stage: 2))
        XCTAssertEqual(running.runningStage, 2, "the active stage, R-Z14")
        XCTAssertTrue(running.isRunning)
        let idle = resolve(status: try status(idleJSON), queued: [try episode("1", "claude-code", hoursAgo: 2)])
        XCTAssertNil(idle.runningStage)
        XCTAssertEqual(idle.mood, .reading)
    }

    /// SSE wins whole-reading, never a hybrid (`resolveSleepDebt` /
    /// `resolveOriginCounts`) — asserted for the page, not only the helpers.
    func test_sseOutranksRest_forTheDebtAndTheOriginCounts() throws {
        let rest = try status(#"{"status":"running","stage":0,"queueByOrigin":{"rss":9},"readByOrigin":{"rss":1},"debt":{"unprocessedCount":99,"oldestUnprocessedAgeHours":null,"hoursSinceLastCycle":1,"hasRunBefore":true,"volumePct":0,"agePct":0,"restedPct":1}}"#)
        let sse = SleepEventPayload(status: "running", restedPct: 40, volumePct: 0, agePct: 0, unprocessedCount: 7,
                                    hasRunBefore: true, hoursSinceLastCycle: 2,
                                    queueByOrigin: ["claude-code": 10], readByOrigin: ["claude-code": 4])
        let page = resolve(status: rest, sse: sse)
        XCTAssertEqual(page.debt?.unprocessedCount, 7)
        XCTAssertEqual(page.read, 4)
        XCTAssertEqual(page.total, 10)
    }

    func test_theQueueIsGroupedOnce_andThePileAndTheOldestWaitReadTheSameRows() throws {
        let queued = [try episode("1", "claude-code", hoursAgo: 72, chars: 5000),
                      try episode("2", "claude-code", hoursAgo: 1),
                      try episode("3", "rss", hoursAgo: 5)]
        let page = resolve(status: try status(idleJSON), queued: queued)
        XCTAssertEqual(page.rows.map(\.origin), ["claude-code", "rss"])
        XCTAssertEqual(page.books.map(\.origin), ["claude-code", "rss"])
        XCTAssertEqual(page.queuedCount, 3)
        XCTAssertEqual(page.oldestWait, "3 days")
        XCTAssertEqual(page.topOriginLabel, OriginIconography.label(for: "claude-code"))
        XCTAssertEqual(page.topOrigin, "claude-code", "the label's mark rides with it")
    }

    func test_theScheduleTheLampAndTheNextRunAreOneReading() throws {
        let daily = ScheduleConfig(mode: "daily", hour: 3, minute: 0)
        let page = resolve(status: try status(idleJSON), schedule: daily,
                           storeStatus: snapshot(nextSleepAt: "2026-09-24T03:00:00Z"))
        XCTAssertTrue(page.lampLit)
        XCTAssertEqual(page.scheduleText, "Every day at 03:00")
        XCTAssertEqual(page.nextRunAt, "Sep 24, 3:00 AM")
        XCTAssertEqual(page.nextRunText, "Next run Sep 24, 3:00 AM")
        let manual = resolve(status: try status(idleJSON))
        XCTAssertFalse(manual.lampLit)
        XCTAssertEqual(manual.nextRunText, Copy.nextRunManual)
    }

    func test_enginesAreNamedOnlyOnceLoaded() throws {
        XCTAssertNil(resolve(status: try status(idleJSON)).manualEngine, "a guessed engine is worse than silence")
        let previews = SleepEnginePreviews(
            manual: SleepEnginePreview(engine: "claude-cli", model: "m", why: "your plan"),
            scheduled: SleepEnginePreview(engine: "ollama", model: "m", why: "a scheduled cycle never spends plan quota"))
        let page = resolve(status: try status(idleJSON), preview: previews)
        XCTAssertEqual(page.manualEngine, "claude-cli")
        XCTAssertEqual(page.scheduledEngineNote, Copy.scheduledRunsOn(engine: "ollama"))
        XCTAssertEqual(page.scheduledEngine, "ollama")
        let same = SleepEnginePreviews(manual: SleepEnginePreview(engine: "ollama", model: "m", why: "w"),
                                       scheduled: SleepEnginePreview(engine: "ollama", model: "m", why: "w"))
        XCTAssertNil(resolve(status: try status(idleJSON), preview: same).scheduledEngine,
                     "named only when it differs, like the note")
    }

    /// Enabled only when the status has loaded, nothing is running and the
    /// queue is non-empty — the button is disabled, never hidden.
    func test_consolidateIsEnabledOnlyWithSomethingToReadAndNothingRunning() throws {
        let one = [try episode("1", "rss", hoursAgo: 1)]
        XCTAssertTrue(resolve(status: try status(idleJSON), queued: one).consolidateEnabled)
        XCTAssertFalse(resolve(status: try status(idleJSON)).consolidateEnabled)
        XCTAssertFalse(resolve(status: nil, queued: one).consolidateEnabled)
        XCTAssertFalse(resolve(status: try status(#"{"status":"running"}"#), queued: one).consolidateEnabled)
    }

    /// The news flags — an empty error or warning string is not news.
    func test_theNewsFlagsIgnoreEmptyStrings() throws {
        let quiet = resolve(status: try status(#"{"status":"idle","error":"","indexWarning":""}"#))
        XCTAssertNil(quiet.cycleError); XCTAssertNil(quiet.indexWarning)
        XCTAssertFalse(quiet.cancelled); XCTAssertFalse(quiet.capped)
        let loud = resolve(status: try status(#"{"status":"idle","error":"boom","indexWarning":"w","cancelled":true,"episodesQueued":9,"episodesTotal":4}"#))
        XCTAssertEqual(loud.cycleError, "boom"); XCTAssertEqual(loud.indexWarning, "w")
        XCTAssertTrue(loud.cancelled); XCTAssertTrue(loud.capped)
        XCTAssertEqual(loud.pips.first, .failed, "the strip freezes where the failure happened (P15)")
    }

    /// Z-P3 — an inbox resolution commit is not a cycle, and neither is a
    /// decay-only one.
    func test_theLastCycleIsTheNewestSleepCommit() throws {
        let history = [try entry("inbox1", kind: "inbox"), try entry("decay1", kind: "decay"),
                       try entry("c0ffee", kind: "sleep", durationMs: 252_000), try entry("older", kind: "sleep")]
        XCTAssertEqual(lastCycleEntry(history)?.commitHash, "c0ffee")
        XCTAssertEqual(resolve(status: try status(idleJSON), history: history).lastCycle?.durationMs, 252_000)
        XCTAssertNil(lastCycleEntry([try entry("inbox1", kind: "inbox")]))
    }

    func test_theInboxCountAndTheQueueLoadPassThrough() throws {
        let page = resolve(status: try status(idleJSON), storeStatus: snapshot(inbox: 4), queueLoad: .loading)
        XCTAssertEqual(page.inboxTotal, 4)
        XCTAssertEqual(page.queueLoad, .loading)
        XCTAssertNil(resolve(status: try status(idleJSON)).inboxTotal, "no snapshot = unknown, not zero")
    }

    // MARK: agePhrase (Z-P21) — ageLabel's thresholds, in words

    func test_agePhrase_isTheLongFormOfAgeLabel() {
        XCTAssertEqual(agePhrase(hours: 0.4), "under an hour")
        XCTAssertEqual(agePhrase(hours: 1.2), "1 hour")
        XCTAssertEqual(agePhrase(hours: 47.9), "47 hours")
        XCTAssertEqual(agePhrase(hours: 72), "3 days")
        XCTAssertEqual(ageLabel(hours: 72), "3d", "the list keeps its compact label")
    }
}
