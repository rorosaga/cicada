import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// 2026-11-26 — a scheduled run the write window refused before it read is a calm notice, never the error state:
/// nothing was read, used or broken, and a retry is usually still pending. The backend says it in `notice` and leaves
/// `error` empty; the page draws one quiet line, and no surface reads the night as a failure.
final class SleepRefusedNightNoticeTests: XCTestCase {

    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private let utc = TimeZone(identifier: "UTC")!
    private let posix = Locale(identifier: "en_US_POSIX")

    private let debt = #""debt":{"unprocessedCount":272,"oldestUnprocessedAgeHours":30,"hoursSinceLastCycle":30,"hasRunBefore":true,"volumePct":60,"agePct":90,"restedPct":10}"#
    private let notice = #""notice":{"kind":"scheduled_run_refused","text":"Last night's 03:00 run hasn't started yet. Next try after 03:12.","detail":"The scheduled run for Nov 24 at 03:00 did not start: something was still writing to your memory, so Sleep read nothing and used nothing. It will try again after 03:12 (try 2 of 4).","retryAt":"2026-11-24T03:12:00+00:00","tries":1,"maxTries":4,"gaveUp":false}"#

    private func status(_ body: String) throws -> SleepStatusResponse {
        try JSONDecoder().decode(SleepStatusResponse.self, from: Data("{\(body)}".utf8))
    }

    private func page(_ status: SleepStatusResponse) -> SleepPageModel {
        SleepPageModel.resolve(status: status, sse: nil, queued: [], schedule: ScheduleConfig(mode: "daily", hour: 3, minute: 0),
                               enginePreview: nil, history: [], storeStatus: nil, queueLoad: .loaded(count: 272),
                               justFinishedAt: nil, intakeInFlight: false, now: now, locale: posix, timeZone: utc)
    }

    func test_theNoticeDecodesLeniently_andAnOlderBackendSendsNone() throws {
        let s = try status(#""status":"idle",\#(notice),\#(debt)"#)
        XCTAssertNil(s.error)
        XCTAssertEqual(s.notice?.text, "Last night's 03:00 run hasn't started yet. Next try after 03:12.")
        XCTAssertEqual(s.notice?.retryAt, "2026-11-24T03:12:00+00:00")
        XCTAssertEqual(s.notice?.tries, 1); XCTAssertEqual(s.notice?.maxTries, 4); XCTAssertEqual(s.notice?.gaveUp, false)
        XCTAssertTrue(s.notice?.detail.contains("read nothing and used nothing") == true)
        XCTAssertNil(try status(#""status":"idle",\#(debt)"#).notice, "an older backend sends none")
        // A kind we do not know, a missing detail and a wrong type are not a decode failure.
        let sparse = try status(#""status":"idle","notice":{"text":"Hello.","tries":"x"},\#(debt)"#)
        XCTAssertEqual(sparse.notice?.text, "Hello."); XCTAssertEqual(sparse.notice?.detail, "Hello.")
        XCTAssertNil(try status(#""status":"idle","notice":{"nope":1},\#(debt)"#).notice, "no text is no notice")
    }

    func test_aRefusedNightIsNeverTheErrorState() throws {
        let model = page(try status(#""status":"idle",\#(notice),\#(debt)"#))
        XCTAssertNil(model.cycleError, "no error: nothing was read")
        XCTAssertNotEqual(model.mood, .error)
        XCTAssertEqual(model.notice?.text, "Last night's 03:00 run hasn't started yet. Next try after 03:12.")
        XCTAssertFalse(model.pips.contains(.failed), "no failed step")
        XCTAssertFalse(model.pips.contains(.skipped), "no frozen stepper")
        XCTAssertFalse(stageStripIsVisible(isRunning: model.isRunning, cancelled: model.stoppedEarly,
                                           failed: model.cycleError != nil), "no stepper at all")
        let line = roomSentence(model.roomContext())
        XCTAssertFalse(line.lead.contains("stopped"), "never \"Reading stopped.\": \(line.lead)")
        XCTAssertNotEqual(line.tone, .warning); XCTAssertNotEqual(line.tailTone, .warning)
        XCTAssertNotEqual(line.tailTone, .danger)
        XCTAssertTrue(line.lead.contains("272"), "the page says what it would without the record: \(line.lead)")
        XCTAssertTrue(model.consolidateEnabled || model.queuedCount == 0, "Consolidate is as live as it would be")
    }

    func test_aRealErrorWinsOverTheNotice() throws {
        let model = page(try status(#""status":"idle","error":"Engine signed out",\#(notice),\#(debt)"#))
        XCTAssertEqual(model.cycleError, "Engine signed out")
        XCTAssertNil(model.notice, "the error is the news; the notice stands down")
        XCTAssertEqual(model.mood, .error)
    }

    func test_aRunningCycleCarriesNoNotice() throws {
        let model = page(try status(#""status":"running","stage":1,\#(notice),\#(debt)"#))
        XCTAssertNil(model.notice)
    }

    func test_gettingStartedDoesNotReadItAsFailed() throws {
        let s = try status(#""status":"idle",\#(notice),\#(debt)"#)
        let step = FirstReadStep.of(FirstReadInputs(running: false, stage: s.stage, error: s.error,
                                                    unprocessed: 272, hasRunBefore: true, pages: 40))
        XCTAssertNotEqual(step, .failed)
        let withError = FirstReadStep.of(FirstReadInputs(running: false, error: "boom", hasRunBefore: true))
        XCTAssertEqual(withError, .failed, "a real error still reads as one")
    }

    func test_theMenuBarWormDoesNotWearTheErrorFaceForIt() throws {
        let snapshot = try JSONDecoder().decode(StatusSnapshot.self, from: Data("""
        {"sleep":{"status":"idle","stage":0,"totalStages":5,"cycleId":null,"error":null,\(notice)},
         "inbox":{"total":0,"byKind":{}},"episodes":{"unprocessed":3,"lastIngestedAt":null}}
        """.utf8))
        XCTAssertNotEqual(deriveBookwormState(snapshot, justFinishedAt: nil, now: now), .error)
    }

    /// The line is drawn where the page puts its quiet notes, and only then: the column is taller with the notice
    /// than the same column without it, and a real error draws none.
    @MainActor
    func test_theQuietLineIsDrawnUnderTheControlsOnlyWhileTheNoticeStands() async throws {
        CicadaTheme.uiScale = 1
        func height(_ status: SleepStatusResponse) async throws -> CGFloat {
            let host = try await SleepRunStripTests.host()
            host.sleep.status = status
            let view = try SleepRunStripTests.column(SleepRunStripTests.page(status), host: host).frame(width: 760)
            let hosting = NSHostingView(rootView: view)
            hosting.frame = NSRect(x: 0, y: 0, width: 760, height: 10)
            return hosting.fittingSize.height
        }
        var plain = try SleepRunStripTests.refusedNight()
        plain = try JSONDecoder().decode(SleepStatusResponse.self, from: {
            var object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(plain)) as! [String: Any]
            object["notice"] = NSNull()
            return try JSONSerialization.data(withJSONObject: object)
        }())
        let withNotice = try await height(SleepRunStripTests.refusedNight())
        let without = try await height(plain)
        XCTAssertGreaterThan(withNotice, without + 8, "one quiet line more")
    }
}
