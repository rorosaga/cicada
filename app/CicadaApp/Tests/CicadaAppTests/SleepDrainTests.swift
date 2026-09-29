import XCTest
@testable import CicadaApp

/// "Consolidate reads everything" (G163, TODO ruling 13) — the app half over the server's real wire.
///
/// `Tests/fixtures/sleep-status-drain.json` is written by the backend's own test
/// (`api/tests/test_sleep_status_app_fixture.py`, four person-started runs through the real pipeline), so
/// every decode, sentence and stop rung below reads what `GET /sleep/status` says, never a hand-typed shape.
final class SleepDrainTests: XCTestCase {

    private let en = Locale(identifier: "en_US")

    private static let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()   // CicadaAppTests
        .deletingLastPathComponent()   // Tests
        .appendingPathComponent("fixtures/sleep-status-drain.json")

    /// One scenario of the fixture: `running` (mid batch 2), `finished`, `plan_limit`, `cancelled`.
    private func scenario(_ name: String, file: StaticString = #filePath, line: UInt = #line) throws -> SleepStatusResponse {
        let all = try JSONSerialization.jsonObject(with: Data(contentsOf: Self.url)) as? [String: Any]
        let object = try XCTUnwrap(all?[name], "no \(name) scenario in \(Self.url.path)", file: file, line: line)
        return try JSONDecoder().decode(SleepStatusResponse.self,
                                        from: JSONSerialization.data(withJSONObject: object))
    }

    private func context(_ status: SleepStatusResponse, mood: BookwormState) -> RoomContext {
        RoomContext(mood: mood, debt: nil, queueLoad: .loaded(count: 1), activeStage: status.stage + 1,
                    read: 3, total: 7, cancelled: status.cancelled, drain: status.drain,
                    scheduleMode: "daily", locale: en)
    }

    // MARK: The decode

    func test_theRunningScenarioDecodesTheDrainBlock() throws {
        let status = try scenario("running")
        let drain = try XCTUnwrap(status.drain)
        XCTAssertEqual(status.status, "running")
        XCTAssertFalse(status.writing, "batch 2 is only reading episodes: no page is held")
        XCTAssertEqual([drain.batch, drain.batches, drain.filed, drain.frozen, drain.batchSize], [2, 3, 3, 7, 3])
        XCTAssertTrue(drain.active)
        XCTAssertFalse(drain.finished)
        XCTAssertNil(drain.stop)
    }

    func test_theFinishedScenario() throws {
        let drain = try XCTUnwrap(try scenario("finished").drain)
        XCTAssertTrue(drain.finished)
        XCTAssertFalse(drain.active)
        XCTAssertEqual([drain.filed, drain.frozen, drain.batches], [7, 7, 3])
        XCTAssertNil(drain.stop)
    }

    func test_thePlanLimitScenarioCarriesTheVendorsSentenceAndResetTime() throws {
        let status = try scenario("plan_limit")
        let stop = try XCTUnwrap(status.drain?.stop)
        XCTAssertEqual(stop.reason, "plan_limit")
        XCTAssertEqual(stop.resetsAt, 1_790_000_000)
        XCTAssertEqual(stop.sentence, "Your Claude plan hit its 5-hour limit — Sleep paused. Try again after 14:00.")
        XCTAssertNil(status.error, "a plan limit is a pause, not a failure")
    }

    func test_aBackendWithoutTheBlockDecodesToNilNotAZero() throws {
        let plain = try JSONDecoder().decode(SleepStatusResponse.self,
                                             from: Data(#"{"status":"idle","stage":0}"#.utf8))
        XCTAssertNil(plain.drain)
        XCTAssertFalse(plain.writing)
        let odd = try JSONDecoder().decode(SleepStatusResponse.self,
                                           from: Data(#"{"status":"idle","drain":{"batch":"x","stop":{"reason":5}}}"#.utf8))
        XCTAssertEqual(odd.drain?.batch, 0, "a field of the wrong type never fails the whole status")
        XCTAssertEqual(odd.drain?.stop?.reason, "error")
    }

    // MARK: The sentence

    func test_theTailNamesTheBatchAndHowMuchIsFiledWhileItReads() throws {
        let status = try scenario("running")
        let line = roomSentence(context(status, mood: .sleeping(stage: 1)))
        XCTAssertEqual(line.tail, "Batch 2 of 3 · 3 of 7 filed.")
    }

    func test_aSingleBatchRunKeepsTheStageDetail() {
        var c = RoomContext(mood: .sleeping(stage: 1), activeStage: 1, read: 1, total: 2, locale: en)
        c.drain = SleepDrainInfo(frozen: 2, batchSize: 25, batch: 1, batches: 1, active: true)
        XCTAssertEqual(roomSentence(c).tail, SleepStages.all[0].detail)
    }

    func test_aPlanStopSaysWhyInTheVendorsWordsAndIsNotAFailure() throws {
        let status = try scenario("plan_limit")
        var c = context(status, mood: .hungry)
        c.debt = SleepDebtView(restedPct: 50, volumePct: 0, agePct: 0, unprocessedCount: 1,
                               hasRunBefore: true, hoursSinceLastCycle: 1)
        let line = roomSentence(c)
        XCTAssertEqual(line.tail, "Your Claude plan hit its 5-hour limit — Sleep paused. Try again after 14:00.")
        XCTAssertEqual(line.tailTone, .warning)
        XCTAssertEqual(line.action, .openDetails(.lastCycle))
    }

    func test_aCancelledRunSaysWhatStaysFiledAndNeverThatNothingWasLost() throws {
        let status = try scenario("cancelled")
        XCTAssertTrue(status.cancelled)
        let line = roomSentence(context(status, mood: .hungry))
        XCTAssertEqual(line.tail, "Stopped — 3 filed stay filed; the rest wait.")
        XCTAssertFalse(try XCTUnwrap(line.tail).contains("nothing was lost"))
    }

    func test_aDrainIsNeverReadAsCappedWhileTheRestIsStillWaiting() throws {
        let status = try scenario("running")
        XCTAssertGreaterThan(status.episodesQueued, status.episodesTotal, "the fixture's mid-run reading")
        let model = SleepPageModel.resolve(
            status: status, sse: nil, queued: [], schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0),
            enginePreview: nil, history: [], storeStatus: nil, queueLoad: .loaded(count: 0),
            justFinishedAt: nil, intakeInFlight: false, locale: en)
        XCTAssertFalse(model.capped)
        XCTAssertEqual(model.drain?.batch, 2)
        XCTAssertEqual(model.roomContext().drain, status.drain)
    }

    // MARK: Cancel and the bank switch

    func test_cancelDoesNotPromiseToStopAfterTheBatchOrThatNothingIsLost() {
        XCTAssertNil(controlCaption(isRunning: false, draining: true))
        XCTAssertEqual(controlCaption(isRunning: true, draining: true), Copy.cancelDrainCaption)
        XCTAssertEqual(controlCaption(isRunning: true), Copy.cancelCaption)
        for text in [Copy.cancelDrainCaption, Copy.cancelDrainExplainer] {
            XCTAssertFalse(text.localizedCaseInsensitiveContains("after this batch"), text)
            XCTAssertFalse(text.localizedCaseInsensitiveContains("nothing is lost"), text)
        }
        XCTAssertTrue(Copy.cancelDrainExplainer.contains("dropped"), "says what is not kept")
    }

    func test_aRefusedBankSwitchShowsTheServersSentenceNotAGenericToast() {
        let body = #"{"detail":"Cicada is reading — stop it first, or wait for it to finish, then switch."}"#
        XCTAssertEqual(BankSwitchFailure.message(APIError.httpError(409, body)),
                       "Cicada is reading — stop it first, or wait for it to finish, then switch.")
        XCTAssertEqual(BankSwitchFailure.message(APIError.httpError(409, "")), Copy.bankSwitchWhileReading)
        XCTAssertEqual(BankSwitchFailure.message(APIError.httpError(404, #"{"detail":"no bank ids"}"#)),
                       BankSwitchFailure.generic, "a 404's detail names ids and is never shown")
        XCTAssertEqual(BankSwitchFailure.message(nil), BankSwitchFailure.generic)
    }
}
