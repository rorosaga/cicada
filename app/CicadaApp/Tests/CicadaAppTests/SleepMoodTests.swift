import XCTest
@testable import CicadaApp

/// G106 amendment: the Sleep debt model's pure Swift-side logic —
/// SSE-vs-REST resolution, mood derivation, and the bracket-text/color
/// presentation. Every case asserts an exact value, not just "didn't throw".
final class SleepMoodTests: XCTestCase {

    // MARK: Fixtures

    /// `SleepStatusResponse` only has `init(from:)` (Codable), so fixtures
    /// round-trip through JSON — mirrors `SleepViewModelTests.sleepStatus`.
    private func status(
        status: String = "idle", stage: Int = 0,
        unprocessedCount: Int = 0, restedPct: Int? = 100,
        volumePct: Int = 0, agePct: Int = 0, hasRunBefore: Bool = true,
        hoursSinceLastCycle: Double? = 0, progressPct: Int? = nil,
        error: String? = nil
    ) throws -> SleepStatusResponse {
        let restedJSON = restedPct.map(String.init) ?? "null"
        let hoursJSON = hoursSinceLastCycle.map { String($0) } ?? "null"
        let progressJSON = progressPct.map(String.init) ?? "null"
        let errorJSON = error.map { "\"\($0)\"" } ?? "null"
        let json = """
        {"status":"\(status)","cycleId":null,"startedAt":null,"progress":null,"error":\(errorJSON),
         "indexWarning":null,"stage":\(stage),"totalStages":5,"episodesTotal":0,
         "entitiesCreated":0,"entitiesUpdated":0,"relationshipsCreated":0,"skillsDetected":0,
         "progressPct":\(progressJSON),
         "debt":{"unprocessedCount":\(unprocessedCount),"oldestUnprocessedAgeHours":null,
                 "hoursSinceLastCycle":\(hoursJSON),"hasRunBefore":\(hasRunBefore),
                 "volumePct":\(volumePct),"agePct":\(agePct),"restedPct":\(restedJSON)}}
        """
        return try JSONDecoder().decode(SleepStatusResponse.self, from: Data(json.utf8))
    }

    private func debtView(
        restedPct: Int? = 100, volumePct: Int = 0, agePct: Int = 0,
        unprocessedCount: Int = 0, hasRunBefore: Bool = true, hoursSinceLastCycle: Double? = 0
    ) -> SleepDebtView {
        SleepDebtView(restedPct: restedPct, volumePct: volumePct, agePct: agePct,
                      unprocessedCount: unprocessedCount, hasRunBefore: hasRunBefore,
                      hoursSinceLastCycle: hoursSinceLastCycle)
    }

    // MARK: resolveSleepDebt — SSE-first, REST fallback

    func test_resolveSleepDebt_prefersSSE_whenItCarriesAnUnprocessedCount() throws {
        let sse = SleepEventPayload(status: "idle", restedPct: 42, volumePct: 10, agePct: 20,
                                     unprocessedCount: 7, hasRunBefore: true, hoursSinceLastCycle: 5)
        let st = try status(unprocessedCount: 99, restedPct: 1)   // deliberately different
        let resolved = resolveSleepDebt(sse: sse, status: st)
        XCTAssertEqual(resolved?.unprocessedCount, 7, "SSE's own full reading wins, not a hybrid")
        XCTAssertEqual(resolved?.restedPct, 42)
    }

    func test_resolveSleepDebt_fallsBackToREST_whenSSEHasNoUnprocessedCount() throws {
        // An SSE payload predating this field (or mid-reconnect) decodes
        // `unprocessedCount` as nil — must not partially trust it.
        let sse = SleepEventPayload(status: "idle")
        let st = try status(unprocessedCount: 3, restedPct: 55)
        let resolved = resolveSleepDebt(sse: sse, status: st)
        XCTAssertEqual(resolved?.unprocessedCount, 3)
        XCTAssertEqual(resolved?.restedPct, 55)
    }

    func test_resolveSleepDebt_fallsBackToREST_whenSSEIsNilEntirely() throws {
        let st = try status(unprocessedCount: 9, restedPct: 12)
        let resolved = resolveSleepDebt(sse: nil, status: st)
        XCTAssertEqual(resolved?.unprocessedCount, 9)
    }

    func test_resolveSleepDebt_isNil_whenNeitherSourceHasAnything() {
        XCTAssertNil(resolveSleepDebt(sse: nil, status: nil))
    }

    func test_resolveProgressPct_prefersSSE_thenFallsBackToREST() throws {
        let sseWithProgress = SleepEventPayload(status: "running", progressPct: 33)
        let st = try status(progressPct: 80)
        XCTAssertEqual(resolveProgressPct(sse: sseWithProgress, status: st), 33)

        let sseWithout = SleepEventPayload(status: "running")
        XCTAssertEqual(resolveProgressPct(sse: sseWithout, status: st), 80)
        XCTAssertNil(resolveProgressPct(sse: nil, status: nil))
    }

    // MARK: deriveSleepPageMood

    func test_mood_isAwake_whenStatusIsNil() {
        XCTAssertEqual(deriveSleepPageMood(status: nil, debt: nil, justFinishedAt: nil), .awake)
    }

    func test_mood_isSleeping_wheneverACycleIsRunning_regardlessOfDebt() throws {
        let st = try status(status: "running", stage: 3)
        let mood = deriveSleepPageMood(status: st, debt: debtView(restedPct: 0, unprocessedCount: 50),
                                        justFinishedAt: nil)
        XCTAssertEqual(mood, .sleeping(stage: 3))
    }

    func test_mood_sleepingStageIsClampedTo1To5() throws {
        let low = try status(status: "running", stage: 0)
        XCTAssertEqual(deriveSleepPageMood(status: low, debt: nil, justFinishedAt: nil), .sleeping(stage: 1))
        let high = try status(status: "running", stage: 9)
        XCTAssertEqual(deriveSleepPageMood(status: high, debt: nil, justFinishedAt: nil), .sleeping(stage: 5))
    }

    func test_mood_isDigesting_within6sOfJustFinished() throws {
        let st = try status(status: "idle")
        let now = Date()
        let mood = deriveSleepPageMood(status: st, debt: debtView(unprocessedCount: 0),
                                        justFinishedAt: now.addingTimeInterval(-3), now: now)
        XCTAssertEqual(mood, .digesting)
    }

    func test_mood_digestingWindowExpiresAt6Seconds() throws {
        let st = try status(status: "idle")
        let now = Date()
        let mood = deriveSleepPageMood(status: st, debt: debtView(unprocessedCount: 0),
                                        justFinishedAt: now.addingTimeInterval(-7), now: now)
        XCTAssertNotEqual(mood, .digesting)
    }

    func test_mood_isHappy_whenQueueIsEmpty() throws {
        let st = try status(status: "idle")
        let mood = deriveSleepPageMood(status: st, debt: debtView(unprocessedCount: 0),
                                        justFinishedAt: nil)
        XCTAssertEqual(mood, .happy)
    }

    func test_mood_isHungry_whenRestedPctAtOrBelow20() throws {
        let st = try status(status: "idle")
        let mood = deriveSleepPageMood(
            status: st,
            debt: debtView(restedPct: 20, unprocessedCount: 30, hoursSinceLastCycle: 1),
            justFinishedAt: nil
        )
        XCTAssertEqual(mood, .hungry)
    }

    func test_mood_isNotHungry_atRestedPct21() throws {
        let st = try status(status: "idle")
        let mood = deriveSleepPageMood(
            status: st,
            debt: debtView(restedPct: 21, unprocessedCount: 30, hoursSinceLastCycle: 1),
            justFinishedAt: nil
        )
        XCTAssertNotEqual(mood, .hungry)
    }

    func test_mood_isHungry_whenGapExceeds48HoursEvenWithHighRestedPct() throws {
        // A pathological but real case: rested% still looks fine (e.g. a
        // small queue that just arrived) but Sleep hasn't run in ages.
        let st = try status(status: "idle")
        let mood = deriveSleepPageMood(
            status: st,
            debt: debtView(restedPct: 90, unprocessedCount: 2, hoursSinceLastCycle: 49),
            justFinishedAt: nil
        )
        XCTAssertEqual(mood, .hungry)
    }

    func test_mood_isNotHungry_atExactly48Hours() throws {
        let st = try status(status: "idle")
        let mood = deriveSleepPageMood(
            status: st,
            debt: debtView(restedPct: 90, unprocessedCount: 2, hoursSinceLastCycle: 48),
            justFinishedAt: nil
        )
        XCTAssertNotEqual(mood, .hungry)
    }

    func test_mood_isCurious_withModerateDebt() throws {
        let st = try status(status: "idle")
        let mood = deriveSleepPageMood(
            status: st,
            debt: debtView(restedPct: 60, unprocessedCount: 12, hoursSinceLastCycle: 5),
            justFinishedAt: nil
        )
        XCTAssertEqual(mood, .curious(count: 12))
    }

    func test_mood_isAwake_whenIdleWithNoDebtReadingYet() throws {
        let st = try status(status: "idle")
        XCTAssertEqual(deriveSleepPageMood(status: st, debt: nil, justFinishedAt: nil), .awake)
    }

    // MARK: sleepDebtBracketText

    func test_bracketText_awake() {
        XCTAssertEqual(sleepDebtBracketText(.awake, debt: nil), "[ awake ]")
    }

    func test_bracketText_sleeping() {
        XCTAssertEqual(sleepDebtBracketText(.sleeping(stage: 2), debt: nil), "[ sleeping · stage 2 of 5 ]")
    }

    func test_bracketText_digesting() {
        XCTAssertEqual(sleepDebtBracketText(.digesting, debt: nil), "[ digesting ]")
    }

    func test_bracketText_happy() {
        XCTAssertEqual(sleepDebtBracketText(.happy, debt: nil), "[ caught up ]")
    }

    func test_bracketText_curious_pluralizesCorrectly() {
        XCTAssertEqual(sleepDebtBracketText(.curious(count: 47), debt: nil), "[ 47 episodes behind ]")
        XCTAssertEqual(sleepDebtBracketText(.curious(count: 1), debt: nil), "[ 1 episode behind ]")
    }

    func test_bracketText_hungry_withEpisodesQueued() {
        let debt = debtView(unprocessedCount: 30)
        XCTAssertEqual(sleepDebtBracketText(.hungry, debt: debt), "[ 30 episodes behind — overdue ]")
    }

    func test_bracketText_hungry_withNoEpisodesButLongGap() {
        let debt = debtView(unprocessedCount: 0)
        XCTAssertEqual(sleepDebtBracketText(.hungry, debt: debt),
                       "[ overdue — hasn't consolidated in a while ]")
    }

    func test_bracketText_hungry_withNilDebt() {
        XCTAssertEqual(sleepDebtBracketText(.hungry, debt: nil),
                       "[ overdue — hasn't consolidated in a while ]")
    }

    func test_bracketText_error() {
        XCTAssertEqual(sleepDebtBracketText(.error, debt: nil), "[ last cycle failed ]")
    }

    func test_bracketColor_errorIsDanger() {
        XCTAssertEqual(sleepDebtBracketColor(.error), CicadaTheme.danger)
    }

    func test_mood_errorWhenLastCycleFailedAndIdle() throws {
        let failed = try status(status: "idle", unprocessedCount: 4, restedPct: 60, error: "RuntimeError: boom")
        XCTAssertEqual(deriveSleepPageMood(status: failed, debt: debtView(restedPct: 60, unprocessedCount: 4), justFinishedAt: nil), .error)
        XCTAssertEqual(deriveSleepPageMood(status: failed, debt: nil, justFinishedAt: Date()), .error, "error beats digesting")
        let running = try status(status: "running", stage: 2, error: "stale error from the previous cycle")
        XCTAssertEqual(deriveSleepPageMood(status: running, debt: nil, justFinishedAt: nil), .sleeping(stage: 2), "a running cycle outranks a stale error")
    }

    // MARK: sleepDebtBracketColor

    func test_bracketColor_hungryIsWarningNeverDanger() {
        XCTAssertEqual(sleepDebtBracketColor(.hungry), CicadaTheme.warning)
        XCTAssertNotEqual(sleepDebtBracketColor(.hungry), CicadaTheme.danger)
    }

    func test_bracketColor_happyIsSuccess() {
        XCTAssertEqual(sleepDebtBracketColor(.happy), CicadaTheme.success)
    }
}
