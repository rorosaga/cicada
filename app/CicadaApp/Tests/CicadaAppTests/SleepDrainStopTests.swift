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

    /// `now` sits just before the fixture's plan reset, so a pause is still a pause unless a test moves the clock.
    private func page(_ status: SleepStatusResponse, sse: SleepEventPayload? = nil,
                      now: Date = Date(timeIntervalSince1970: 1_789_999_000)) -> SleepPageModel {
        SleepPageModel.resolve(
            status: status, sse: sse, queued: [], schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0),
            enginePreview: nil, history: [], storeStatus: nil, queueLoad: .loaded(count: 0),
            justFinishedAt: nil, intakeInFlight: false, now: now, locale: en)
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
        // The wire's `batches` is the plan (3) and one was dropped: the stopped row never counts batches.
        XCTAssertEqual(rows[1].title, "Where it stopped")
        XCTAssertEqual(rows[1].text, "6 of 7 filed stay filed; the rest wait for the next Consolidate.")
        XCTAssertFalse(rows[1].text.contains("batch"))
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
        // A drain that filed nothing still drops the batch that was reading: never "nothing was lost".
        XCTAssertEqual(none.first?.text, Copy.SleepDetailsWords.cancelledDrainNoneText())
        XCTAssertFalse(none.first?.text.contains("nothing was lost") ?? true)
        // No drain at all: the standing one-batch copy.
        let plain = LastCycleRow.rows(pageError: nil, cancelled: true, capped: false, indexWarning: nil,
                                      status: status, locale: en)
        XCTAssertEqual(plain.first?.text, Copy.SleepDetailsWords.cancelledText)
    }

    private func scenarioWithoutCancelFlag(_ name: String) throws -> SleepStatusResponse {
        let all = try JSONSerialization.jsonObject(with: Data(contentsOf: Self.url)) as? [String: Any]
        var object = try XCTUnwrap(all?[name] as? [String: Any])
        object["cancelled"] = false
        return try JSONDecoder().decode(SleepStatusResponse.self, from: JSONSerialization.data(withJSONObject: object))
    }

    func test_aStoppedRunKeepsSayingSoAfterTheCancelWindowWithoutAFalseTitle() throws {
        let status = try scenarioWithoutCancelFlag("cancelled")
        let drain = try XCTUnwrap(status.drain)
        let rows = LastCycleRow.rows(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                     status: status, drain: drain, locale: en)
        XCTAssertEqual(rows.map(\.kind), [.drain])
        XCTAssertEqual(rows[0].title, "Cancelled")
        XCTAssertFalse(rows[0].title.contains("Read everything"))
        XCTAssertFalse(rows[0].text.contains("batch"))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                                drain: drain))
        // Inside the window the cancel row already says it: no second row.
        let inside = LastCycleRow.rows(pageError: nil, cancelled: true, capped: false, indexWarning: nil,
                                       status: status, drain: drain, locale: en)
        XCTAssertEqual(inside.map(\.kind), [.cancelled])
        // An engine stop says how much stays filed too.
        var engine = drain
        engine.stop = SleepDrainInfo.Stop(reason: "engine")
        let stopped = LastCycleRow.rows(pageError: "boom", cancelled: false, capped: false, indexWarning: nil,
                                        status: status, drain: engine, locale: en)
        XCTAssertEqual(stopped.map(\.kind), [.failed, .drain])
        XCTAssertEqual(stopped[1].title, "Where it stopped")
    }

    func test_aCancelledStripDoesNotStayFrozenPastTheBackendsWindow() throws {
        let status = try scenarioWithoutCancelFlag("cancelled")
        let model = page(status)
        XCTAssertFalse(model.cancelled)
        XCTAssertFalse(model.stoppedEarly)
        XCTAssertFalse(stageStripIsVisible(isRunning: model.isRunning, cancelled: model.stoppedEarly,
                                           failed: model.cycleError != nil))
    }

    func test_aPlanPauseRetiresWhenItsResetTimePasses() throws {
        let status = try scenario("plan_limit")
        let reset = try XCTUnwrap(status.drain?.stop?.resetsAt)
        func model(at seconds: Int) -> SleepPageModel {
            SleepPageModel.resolve(
                status: status, sse: nil, queued: [], schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0),
                enginePreview: nil, history: [], storeStatus: nil, queueLoad: .loaded(count: 0),
                justFinishedAt: nil, intakeInFlight: false,
                now: Date(timeIntervalSince1970: TimeInterval(seconds)), locale: en)
        }
        let before = model(at: reset - 60), after = model(at: reset + 60)
        XCTAssertTrue(before.stoppedEarly)
        XCTAssertFalse(before.planPauseLapsed)
        XCTAssertFalse(after.stoppedEarly)
        XCTAssertTrue(after.planPauseLapsed)
        let lead = roomSentence(after.roomContext(locale: en))
        XCTAssertNotEqual(lead.tail, status.drain?.stop?.sentence)
        XCTAssertNotEqual(lead.tailTone, .warning)
        XCTAssertEqual(roomSentence(before.roomContext(locale: en)).tailTone, .warning)
        let rows = LastCycleRow.rows(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                     status: status, drain: status.drain, planPauseLapsed: true, locale: en)
        XCTAssertEqual(rows.map(\.kind), [.drain], "the paused row goes with the pause; the fact that it stopped stays")
    }

    func test_aLongVendorSentenceIsNeverClippedInTheTail() throws {
        let status = try scenario("plan_limit")
        var c = RoomContext(mood: .hungry, locale: en)
        var drain = try XCTUnwrap(status.drain)
        drain.stop?.sentence = "Your Claude plan hit its weekly limit after a very long run of reading, so Sleep paused itself. Try again after Friday 14:00."
        c.drain = drain
        let line = roomSentence(c)
        XCTAssertFalse(try XCTUnwrap(line.tail).contains("…"))
        XCTAssertTrue(try XCTUnwrap(line.tail).contains("Details"))
        XCTAssertEqual(line.action, .openDetails(.lastCycle))
    }

    func test_aCancelInBatchOneNeverSaysNothingWasLost() throws {
        var c = RoomContext(mood: .hungry, locale: en)
        c.cancelled = true
        c.drain = SleepDrainInfo(frozen: 7, batchSize: 3, batch: 1, batches: 3, filed: 0,
                                 stop: SleepDrainInfo.Stop(reason: "cancelled"))
        let tail = roomSentence(c).tail
        XCTAssertFalse(try XCTUnwrap(tail).contains("nothing was lost"))
        XCTAssertLessThanOrEqual(try XCTUnwrap(tail).count, SentenceLine.maxTail)
        c.drain = nil
        XCTAssertEqual(roomSentence(c).tail, "Stopped early — nothing was lost.")
    }

    func test_aMultiBatchRunTitlesTheCostAndDurationAsTheLastBatch() throws {
        let status = try scenario("finished")
        let drain = try XCTUnwrap(status.drain)
        XCTAssertGreaterThan(drain.batches, 1)
        let rows = LastCycleRow.rows(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                     status: status, usageLine: "12 calls", drain: drain, locale: en)
        XCTAssertEqual(rows.last?.title, Copy.SleepUsage.lastBatchTitle)
        let one = LastCycleRow.rows(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                    status: status, usageLine: "12 calls", locale: en)
        XCTAssertEqual(one.last?.title, Copy.SleepUsage.lastCycleTitle)
        let took = readoutRows(entityCount: 1, sourceCount: 1, lastDurationMs: 1000, lastEngine: nil, engineDetail: nil,
                               lastIsOneBatch: true, locale: en).first { $0.id == "lastCycle" }
        XCTAssertEqual(took?.key, "Last batch took")
    }

    func test_theProjectWritesGateStillKeysOffRunningAndSaysSo() {
        XCTAssertTrue(Copy.Projects.sleepRunningHelp.contains("Sleep is running"))
        XCTAssertFalse(Copy.Projects.sleepRunningHelp.contains("writing"))
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
