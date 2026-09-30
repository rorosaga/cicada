import XCTest
@testable import CicadaApp

/// "Consolidate reads everything" (G163), the second half of the app: the SSE overlay, what a plan pause
/// does to the strip, the mood and the cheer, Details' rows, and Home's row after an early stop.
final class SleepDrainStopTests: XCTestCase {

    private let en = Locale(identifier: "en_US")

    private static let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("fixtures/sleep-status-drain.json")

    private func scenario(_ name: String) throws -> SleepStatusResponse {
        let all = try JSONSerialization.jsonObject(with: Data(contentsOf: Self.url)) as? [String: Any]
        let object = try XCTUnwrap(all?[name])
        return try JSONDecoder().decode(SleepStatusResponse.self,
                                        from: JSONSerialization.data(withJSONObject: object))
    }

    private func page(_ status: SleepStatusResponse, sse: SleepEventPayload? = nil) -> SleepPageModel {
        SleepPageModel.resolve(
            status: status, sse: sse, queued: [], schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0),
            enginePreview: nil, history: [], storeStatus: nil, queueLoad: .loaded(count: 0),
            justFinishedAt: nil, intakeInFlight: false, locale: en)
    }

    // MARK: SSE overlay

    func test_theSSEBlockDecodesLeniently() throws {
        let event = try JSONDecoder().decode(
            SleepEventPayload.self,
            from: Data(#"{"status":"running","drain":{"batch":2,"batches":3,"filed":3,"frozen":7,"active":true,"stop":null}}"#.utf8))
        XCTAssertEqual(event.drain, SleepDrainSSE(batch: 2, batches: 3, filed: 3, frozen: 7, active: true, stop: nil))
        let old = try JSONDecoder().decode(SleepEventPayload.self, from: Data(#"{"status":"idle"}"#.utf8))
        XCTAssertNil(old.drain, "an older backend sends no block")
    }

    func test_theSSEOverlaysTheMovingCountsOfTheSameRunOnly() throws {
        let status = try scenario("running")
        let base = try XCTUnwrap(status.drain)
        var event = SleepEventPayload(status: "running", drain: SleepDrainSSE(
            batch: base.batch + 1, batches: base.batches, filed: base.filed + 3, frozen: base.frozen, active: true))
        let live = try XCTUnwrap(resolveDrain(sse: event, status: status))
        XCTAssertEqual([live.batch, live.filed], [base.batch + 1, base.filed + 3])
        XCTAssertEqual(live.batchSize, base.batchSize, "the rest of the block is the status's")

        event.drain = SleepDrainSSE(batch: 9, batches: 9, filed: 9, frozen: base.frozen + 1, active: true)
        XCTAssertEqual(resolveDrain(sse: event, status: status), base, "a different run's counts are never mixed in")
    }

    func test_theSSEStandsInBeforeTheStatusHasLandedAndNeverInventsAStopSentence() {
        let event = SleepEventPayload(status: "idle", drain: SleepDrainSSE(
            batch: 2, batches: 3, filed: 3, frozen: 7, active: false, stop: "plan_limit"))
        let drain = resolveDrain(sse: event, status: nil)
        XCTAssertEqual(drain?.stop?.reason, "plan_limit")
        XCTAssertNil(drain?.stop?.sentence)
        XCTAssertNil(resolveDrain(sse: nil, status: nil))
    }

    // MARK: A plan pause is not a finish

    func test_aPlanPauseFreezesTheStripAndDoesNotChewOrCheer() throws {
        let status = try scenario("plan_limit")
        let model = page(status)
        XCTAssertFalse(model.cancelled)
        XCTAssertTrue(model.stoppedEarly)
        XCTAssertTrue(stageStripIsVisible(isRunning: model.isRunning, cancelled: model.stoppedEarly,
                                          failed: model.cycleError != nil))
        XCTAssertFalse(model.pips.contains(.pending), "stages that never ran are skipped, not pending")
        XCTAssertFalse(isRealCompletion(old: "running", new: "idle", cancelled: false, error: nil,
                                        drainStop: status.drain?.stop?.reason))
        XCTAssertNotEqual(deriveSleepPageMood(status: status, debt: nil, justFinishedAt: Date(), now: Date()),
                          .digesting)
    }

    func test_aFinishedRunStillCheers() throws {
        let status = try scenario("finished")
        XCTAssertFalse(page(status).stoppedEarly)
        XCTAssertTrue(isRealCompletion(old: "running", new: "idle", cancelled: false, error: nil,
                                       drainStop: status.drain?.stop?.reason))
    }

    // MARK: Details

    func test_detailsShowsTheDrainRowInsteadOfTheCapRow() throws {
        let status = try scenario("finished")
        let drain = try XCTUnwrap(status.drain)
        let rows = LastCycleRow.rows(pageError: nil, cancelled: false, capped: true, indexWarning: nil,
                                     status: status, drain: drain, locale: en)
        XCTAssertEqual(rows.map(\.kind), [.drain])
        XCTAssertEqual(rows[0].title, "Read everything")
        XCTAssertEqual(rows[0].text, "7 of 7 filed · 3 batches")
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                                drain: drain))
    }

    func test_aOneBatchRunNeedsNoRowOfItsOwn() {
        let drain = SleepDrainInfo(frozen: 5, batchSize: 25, batch: 1, batches: 1, filed: 5, finished: true)
        XCTAssertFalse(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                                 drain: drain))
    }

    func test_aPlanPauseRowCarriesTheVendorsWholeSentence() throws {
        let status = try scenario("plan_limit")
        let drain = try XCTUnwrap(status.drain)
        let rows = LastCycleRow.rows(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                     status: status, drain: drain, locale: en)
        XCTAssertEqual(rows.map(\.kind), [.paused, .drain])
        XCTAssertEqual(rows[0].text, drain.stop?.sentence)
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                                drain: drain))
    }

    func test_aCancelAfterFiledBatchesNeverSaysBeforeAnyWrites() throws {
        let status = try scenario("cancelled")
        let drain = try XCTUnwrap(status.drain)
        let rows = LastCycleRow.rows(pageError: nil, cancelled: true, capped: false, indexWarning: nil,
                                     status: status, drain: drain, locale: en)
        let cancelled = try XCTUnwrap(rows.first { $0.kind == .cancelled })
        XCTAssertEqual(cancelled.text, Copy.SleepDetailsWords.cancelledDrainText(filed: drain.filed, frozen: drain.frozen, locale: en))
        XCTAssertFalse(cancelled.text.contains("before any writes"))
        // Nothing filed yet: the old words are true.
        let none = LastCycleRow.rows(pageError: nil, cancelled: true, capped: false, indexWarning: nil,
                                     status: status, drain: SleepDrainInfo(frozen: 5, batch: 1, batches: 1),
                                     locale: en)
        XCTAssertEqual(none.first?.text, Copy.SleepDetailsWords.cancelledText)
    }

    func test_theRequeuedCountIsSaidPlainly() {
        XCTAssertEqual(Copy.SleepDetailsWords.drainText(filed: 20, frozen: 23, batches: 1, requeued: 3, locale: en),
                       "20 of 23 filed · 1 batch · 3 will be read next time")
    }

    // MARK: Home and the lamp

    func test_homeSaysKeepReadingAfterAnEarlyStopNotTheNextN() {
        XCTAssertEqual(FirstReadStep.capped(read: 50, left: 9).action, .keepReading)
        XCTAssertEqual(Copy.gsKeepReading, "Keep reading")
    }

    func test_aFullDrainReadsAsFinishedOnHome() {
        var inputs = FirstReadInputs()
        inputs.hasRunBefore = true
        inputs.episodesQueued = 287
        inputs.episodesTotal = 287
        inputs.unprocessed = 0
        inputs.pages = 40
        XCTAssertEqual(FirstReadStep.of(inputs), .finished(pages: 40))
    }

    func test_theLampSaysAScheduledRunReadsOneBatch() {
        XCTAssertEqual(Copy.scheduledReadsOneBatch(size: 25, locale: en),
                       "A scheduled run reads one batch of 25; Consolidate reads everything waiting.")
    }
}
