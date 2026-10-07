import XCTest
@testable import CicadaApp

// Sleep page v5 (G163; TODO rulings 13, 15, 16) — the app half, over the backend's own fixtures
// (`test_sleep_v5_app_fixtures.py` and `test_sleep_status_app_fixture.py` write them), so a wire drift fails on one
// side. One file, one class per concern, each named for what the plan asked it to prove.

private enum V5Fixture {
    static let dir = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("fixtures")

    static func object(_ file: String) throws -> Any {
        try JSONSerialization.jsonObject(with: Data(contentsOf: dir.appendingPathComponent(file)))
    }

    static func decode<T: Decodable>(_ type: T.Type, _ file: String, key: String? = nil) throws -> T {
        var value = try object(file)
        if let key { value = try XCTUnwrap((value as? [String: Any])?[key], "no scenario \(key) in \(file)") }
        return try JSONDecoder().decode(T.self, from: JSONSerialization.data(withJSONObject: value))
    }

    static func paused(_ reason: String) throws -> SleepStatusResponse {
        try decode(SleepStatusResponse.self, "sleep-status-paused.json", key: reason)
    }

    static func drain(_ scenario: String) throws -> SleepStatusResponse {
        try decode(SleepStatusResponse.self, "sleep-status-drain.json", key: scenario)
    }

    static let en = Locale(identifier: "en_US")
    static let utc = TimeZone(identifier: "UTC")!
    /// Before every fixture's reset time (1_790_003_600), the same UTC day.
    static let now = Date(timeIntervalSince1970: 1_790_000_000)

    static func page(_ status: SleepStatusResponse?, sse: SleepEventPayload? = nil, pausing: Bool = false,
                     batchSize: Int? = nil) -> SleepPageModel {
        SleepPageModel.resolve(
            status: status, sse: sse, queued: [], schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0),
            enginePreview: nil, history: [], storeStatus: nil, queueLoad: .loaded(count: 0),
            justFinishedAt: nil, intakeInFlight: false, paused: status?.paused, batchSize: batchSize,
            pausing: pausing, now: now, locale: en, timeZone: utc)
    }

    static func sentence(_ page: SleepPageModel) -> SentenceLine { roomSentence(page.roomContext(locale: en)) }

    static func entries(_ json: String) throws -> [SleepHistoryEntry] {
        try JSONDecoder().decode([SleepHistoryEntry].self, from: Data(json.utf8))
    }

    /// Every provider or model name a Sleep string must not say as the one doing a job (owner, 2026-09-30).
    static let providerWords = ["Claude", "ChatGPT", "Anthropic", "OpenAI", "Ollama", "OpenRouter", "Gemini", "Haiku",
                                "Sonnet", "Opus", "GPT", "Codex", "Mistral", "Groq", "xAI", "Grok"]
    /// What no string may promise without a journal of paid answers (G163 SL-1).
    static let journalWords = ["read and kept", "Saved reading", "already read, at no cost", "Nothing read is lost",
                               "nothing read is lost"]
}

// MARK: - Wire

final class SleepV5WireTests: XCTestCase {
    func test_everyPausedScenarioDecodesWithItsReason() throws {
        for reason in ["user", "reserve", "plan_window", "engine", "restart"] {
            let status = try V5Fixture.paused(reason)
            let paused = try XCTUnwrap(status.paused, reason)
            XCTAssertEqual(paused.reason, reason)
            XCTAssertEqual(status.status, "idle", "a paused run is idle — it holds nothing")
            XCTAssertTrue(paused.canContinue)
            XCTAssertGreaterThan(paused.frozen, paused.filed)
        }
        let reserve = try XCTUnwrap(V5Fixture.paused("reserve").paused)
        XCTAssertEqual(reserve.autoContinue?.armed, true)
        XCTAssertEqual(reserve.limit, "five_hour")
        XCTAssertNotNil(reserve.resetsAt)
        XCTAssertNil(try V5Fixture.paused("restart").paused?.autoContinue)
    }

    func test_theRunningDrainCarriesTheV5Counters() throws {
        let drain = try XCTUnwrap(V5Fixture.drain("running").drain)
        XCTAssertEqual(drain.startedBy, "user")
        XCTAssertEqual(drain.firstRun, true)
        XCTAssertNotNil(drain.batchState)
        XCTAssertEqual(drain.stages?.map(\.id), ["read", "sort", "decide", "notice", "file"])
        let origin = try XCTUnwrap(drain.byOrigin?.values.first)
        XCTAssertEqual(origin.frozen,
                       origin.filed + origin.read + origin.waiting + origin.couldNotBeRead + origin.parked + origin.skipped)
    }

    func test_theRunDetailOptionsAndQueueDecode() throws {
        let detail = try V5Fixture.decode(SleepRunDetail.self, "sleep-run-detail.json")
        XCTAssertFalse(detail.batches.isEmpty)
        XCTAssertFalse(detail.models.isEmpty)
        XCTAssertFalse(detail.models.flatMap(\.stages).isEmpty, "a model's stages are the ledger's own data")
        let defaults = try V5Fixture.decode(SleepRunOptions.self, "sleep-run-options.json", key: "defaults")
        XCTAssertEqual(defaults.batchSizeChoices, [10, 25, 50])
        XCTAssertFalse(defaults.continueAfterReset, "ruling 15: off by default")
        XCTAssertNil(defaults.reservePct, "Leave room in my plan: off by default")
        let custom = try V5Fixture.decode(SleepRunOptions.self, "sleep-run-options.json", key: "custom")
        XCTAssertEqual(custom.batchSize, 10)
        let queue = try V5Fixture.decode(SleepQueueResponse.self, "sleep-queue.json")
        XCTAssertTrue(queue.items.contains { $0.state == "could_not_be_read" && $0.reason == "empty_answer" })
    }

    func test_anOlderBackendReadsAsNoNews() throws {
        let body = #"{"status":"idle","stage":0,"totalStages":5,"debt":{"unprocessedCount":4,"hasRunBefore":true,"volumePct":0,"agePct":0}}"#
        let status = try? JSONDecoder().decode(SleepStatusResponse.self, from: Data(body.utf8))
        XCTAssertNil(status?.paused)
        XCTAssertEqual(status?.debt.parkedCount, 0)
        XCTAssertEqual(status?.debt.readable, 4)
        let event = try JSONDecoder().decode(SleepEventPayload.self, from: Data(#"{"status":"idle"}"#.utf8))
        XCTAssertFalse(event.pausedKnown)
        let current = try JSONDecoder().decode(SleepEventPayload.self, from: Data(#"{"status":"idle","paused":null}"#.utf8))
        XCTAssertTrue(current.pausedKnown, "a current backend's null means: nothing is paused")
        XCTAssertNil(current.paused)
        let entry = try V5Fixture.entries(#"[{"commitHash":"a","date":"2026-09-30","message":"m","filesChanged":[],"kind":"sleep","entitiesCreated":0,"entitiesUpdated":0,"episodes":0,"sessions":0,"authors":[]}]"#)
        XCTAssertNil(entry.first?.drainId)
    }

    func test_optionsChangesSendOnlyTheirField() {
        XCTAssertEqual(SleepRunOptionsChange.batchSize(50).body as? [String: Int], ["batchSize": 50])
        XCTAssertEqual(SleepRunOptionsChange.continueAfterReset(true).body as? [String: Bool], ["continueAfterReset": true])
        XCTAssertTrue(SleepRunOptionsChange.reservePct(nil).body["reservePct"] is NSNull, "off is an explicit null")
    }
}

// MARK: - The sentence ladder

final class SleepV5RoomSentenceTests: XCTestCase {
    func test_aTimeoutPauseSaysItCanBeTriedAgainAndOffersContinue() {
        let diagnosis = "The engine timed out. Continue to try again; the part it was reading will be read again."
        let paused = SleepPausedRun(reason: "engine", sentence: diagnosis, filed: 3, frozen: 9)
        let page = SleepPageModel.resolve(
            status: nil, sse: nil, queued: [], schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0),
            enginePreview: nil, history: [], storeStatus: nil, queueLoad: .loaded(count: 6),
            justFinishedAt: nil, intakeInFlight: false, paused: paused, now: V5Fixture.now, locale: V5Fixture.en)
        let line = V5Fixture.sentence(page)
        XCTAssertEqual(line.lead, "Paused. The engine stopped answering.")
        XCTAssertEqual(line.tail, "Continue to try again. 3 of 9 filed.")
        XCTAssertTrue(page.paused?.canContinue == true)
        XCTAssertFalse(page.consolidateEnabled)
        let rows = LastCycleRow.runRows(drain: nil, paused: paused, run: nil, detail: nil, parkedCount: 0,
                                        runBilling: nil, reserveValue: nil, locale: V5Fixture.en)
        XCTAssertEqual(rows.first { $0.kind == .paused }?.text, diagnosis)
        XCTAssertNil(page.autoContinueWhen)
    }

    func test_everyV5SentenceFitsAndPromisesNothingUntrue() {
        for sentence in Copy.sleepV5Sentences where !sentence.isEmpty {
            for word in V5Fixture.journalWords {
                XCTAssertFalse(sentence.contains(word), "\(sentence) promises a journal that does not exist")
            }
            XCTAssertFalse(sentence.contains("$"), sentence)
        }
    }

    func test_theLeadsFitFortyAndTheTailsEighty() {
        let leads = [Copy.SleepV5.sortingLead(31, 86), Copy.SleepV5.decidingLead(4, 12), Copy.SleepV5.filingLead,
                     Copy.SleepV5.pausingLead, Copy.SleepV5.pausedLead, Copy.SleepV5.pausedReserveLead,
                     Copy.SleepV5.pausedPlanWindowLead, Copy.SleepV5.pausedPlanWeeklyLead,
                     Copy.SleepV5.pausedOverageLead, Copy.SleepV5.pausedEngineLead, Copy.SleepV5.restartLead,
                     Copy.SleepV5.bankSwitchedLead, Copy.SleepV5.filedLead(286)]
        for lead in leads { XCTAssertLessThanOrEqual(lead.count, SentenceLine.maxLead, lead) }
        let tails = [Copy.SleepV5.firstNightTail(batchSize: 25), Copy.SleepV5.sortingTail, Copy.SleepV5.decidingTail,
                     Copy.SleepV5.firstSaveTail(filed: 25, beliefs: 31), Copy.SleepV5.pausingTail,
                     Copy.SleepV5.pausedByYouTail(filed: 74, frozen: 287),
                     Copy.SleepV5.continueWhenYouLike(filed: 98, frozen: 287),
                     Copy.SleepV5.continuesAfter("3:40 PM", filed: 98, frozen: 287),
                     Copy.SleepV5.resetsContinue("after 2:00 PM"), Copy.SleepV5.continueToTryAgain(filed: 98, frozen: 287),
                     Copy.SleepV5.restartTail(filed: 98, frozen: 287), Copy.SleepV5.bankSwitchedTail]
        for tail in tails { XCTAssertLessThanOrEqual(tail.count, SentenceLine.maxTail, tail) }
    }

    func test_theRungsForEachPause() throws {
        let user = V5Fixture.sentence(V5Fixture.page(try V5Fixture.paused("user")))
        XCTAssertEqual(user.lead, "Paused.")
        XCTAssertEqual(user.tail, "3 of 9 filed. The part it was reading is read again.")

        let reserve = V5Fixture.sentence(V5Fixture.page(try V5Fixture.paused("reserve")))
        XCTAssertEqual(reserve.lead, "Paused to leave room in your plan.")
        XCTAssertTrue(reserve.tail?.hasPrefix("Continues after ") == true, reserve.tail ?? "")
        XCTAssertTrue(reserve.tail?.hasSuffix("4 of 9 filed.") == true)

        let window = V5Fixture.sentence(V5Fixture.page(try V5Fixture.paused("plan_window")))
        XCTAssertEqual(window.lead, "Paused. Your plan window is full.")

        let engine = V5Fixture.sentence(V5Fixture.page(try V5Fixture.paused("engine")))
        XCTAssertEqual(engine.lead, "Paused. The engine stopped answering.")
        XCTAssertEqual(engine.tail, "Continue to try again. 3 of 9 filed.")

        let restart = V5Fixture.sentence(V5Fixture.page(try V5Fixture.paused("restart")))
        XCTAssertEqual(restart.lead, "Cicada restarted while reading.")
        XCTAssertEqual(restart.tail, "3 of 9 filed. Continue when you like.")
    }

    func test_aPausedSentenceNamesNoProvider() throws {
        for reason in ["user", "reserve", "plan_window", "engine", "restart"] {
            let line = V5Fixture.sentence(V5Fixture.page(try V5Fixture.paused(reason)))
            for word in V5Fixture.providerWords {
                XCTAssertFalse(line.lead.contains(word), "\(reason): \(line.lead)")
                XCTAssertFalse((line.tail ?? "").contains(word), "\(reason): \(line.tail ?? "")")
            }
        }
    }

    func test_pausingSaysTheSafePointNotAPromise() throws {
        let running = try V5Fixture.drain("running")
        let line = V5Fixture.sentence(V5Fixture.page(running, pausing: true))
        XCTAssertEqual(line.lead, "Pausing.")
        XCTAssertEqual(line.tail, "Stopping at the next safe point. What is filed stays filed.")
    }

    func test_theFirstNightSaysHowOftenItSaves() {
        XCTAssertEqual(Copy.SleepV5.firstNightTail(batchSize: 10, V5Fixture.en),
                       "My first night. I'll read all of them, saving every 10.")
    }

    func test_oneClockFormatterForEveryResetTime() {
        let today = Date(timeIntervalSince1970: 1_790_003_600)
        let sameDay = sleepClockWords(today, now: V5Fixture.now, locale: V5Fixture.en, timeZone: V5Fixture.utc,
                                      afterToday: true)
        XCTAssertTrue(sameDay.hasPrefix("after "), sameDay)
        let tomorrow = sleepClockWords(today.addingTimeInterval(86_400), now: V5Fixture.now, locale: V5Fixture.en,
                                       timeZone: V5Fixture.utc, afterToday: true)
        XCTAssertFalse(tomorrow.hasPrefix("after "), "another day names its weekday: \(tomorrow)")
    }
}

// MARK: - Paused state

final class SleepV5PausedStateTests: XCTestCase {
    func test_aPausedRunOffersContinueNotConsolidate() throws {
        let page = V5Fixture.page(try V5Fixture.paused("user"))
        XCTAssertNotNil(page.paused)
        XCTAssertFalse(page.consolidateEnabled, "the one primary is Continue while a run is paused (DR-40)")
    }

    func test_aPausedRunIsTheWormAtItsDeskNeverAFailureOrACheer() throws {
        for reason in ["user", "reserve", "plan_window", "engine", "restart"] {
            let page = V5Fixture.page(try V5Fixture.paused(reason))
            XCTAssertEqual(page.mood, .reading, reason)
        }
    }

    func test_aWeeklyLimitHoldsContinueUntilItsReset() throws {
        var status = try V5Fixture.paused("plan_window")
        var paused = try XCTUnwrap(status.paused)
        paused.reason = "plan_weekly"
        status = try reencode(status, paused: paused)
        XCTAssertTrue(V5Fixture.page(status).continueWaitsForReset)
        XCTAssertFalse(V5Fixture.page(try V5Fixture.paused("plan_window")).continueWaitsForReset)
    }

    func test_nothingPausedWhileARunReads() throws {
        let page = V5Fixture.page(try V5Fixture.drain("running"))
        XCTAssertNil(page.paused)
    }

    private func reencode(_ status: SleepStatusResponse, paused: SleepPausedRun) throws -> SleepStatusResponse {
        var object = try XCTUnwrap(V5Fixture.object("sleep-status-paused.json") as? [String: Any])["plan_window"] as? [String: Any]
        object?["paused"] = try JSONSerialization.jsonObject(with: JSONEncoder().encode(paused))
        return try JSONDecoder().decode(SleepStatusResponse.self,
                                        from: JSONSerialization.data(withJSONObject: try XCTUnwrap(object)))
    }
}

// MARK: - The bar

final class SleepV5ProgressBarTests: XCTestCase {
    private func drain(filed: Int, read: Int, waiting: Int, failed: Int, parked: Int = 0, active: Bool = true,
                       calls: Int = 324) -> SleepDrainInfo {
        var d = try! JSONDecoder().decode(SleepDrainInfo.self, from: Data(#"{"frozen":0}"#.utf8))
        d.frozen = filed + read + waiting + failed + parked
        d.filed = filed
        d.active = active
        d.calls = calls
        d.batchState = .init(index: 3, of: 12, total: 25, read: read, reading: 3, failed: failed)
        d.byOrigin = ["chatgpt-export": .init(frozen: d.frozen, filed: filed, read: read, waiting: waiting,
                                              couldNotBeRead: failed, parked: parked)]
        return d
    }

    func test_theTermsAddUpToWhatTheRunSetOutToRead() throws {
        for (filed, read, waiting, failed) in [(0, 0, 287, 0), (50, 14, 222, 1), (286, 0, 0, 1)] {
            let p = try XCTUnwrap(RunProgress.from(drain(filed: filed, read: read, waiting: waiting, failed: failed)))
            XCTAssertEqual(p.filed + p.read + p.waiting + p.couldNotBeRead, p.frozen)
        }
    }

    func test_theAccessibilityValueSaysEveryTermInWords() throws {
        let p = try XCTUnwrap(RunProgress.from(drain(filed: 50, read: 14, waiting: 222, failed: 1)))
        XCTAssertEqual(p.accessibilityValue(locale: V5Fixture.en),
                       "50 filed, 14 read, waiting to file, 222 waiting, 1 could not be read, 324 calls made")
    }

    func test_aPausedRunShowsNothingAsRead() throws {
        let p = try XCTUnwrap(RunProgress.from(drain(filed: 98, read: 9, waiting: 180, failed: 0, active: false)))
        XCTAssertEqual(p.read, 0, "without a journal the part in progress is read again — never shown as kept")
    }

    func test_noBarForAnOlderBackend() {
        let old = try! JSONDecoder().decode(SleepDrainInfo.self, from: Data(#"{"frozen":7,"filed":3}"#.utf8))
        XCTAssertNil(RunProgress.from(old))
    }
}

// MARK: - The strip

final class SleepV5StagesTests: XCTestCase {
    private func stages(sort: (Int, Int?), decide: (Int, Int?)) -> [SleepDrainInfo.Stage] {
        [.init(id: "read", done: 25, total: 25, state: "done"),
         .init(id: "sort", done: sort.0, total: sort.1, state: "active"),
         .init(id: "decide", done: decide.0, total: decide.1),
         .init(id: "notice"), .init(id: "file")]
    }

    func test_sortAndDecideFillOnlyFromAFixedTotal() {
        let pips = stageStripState(stage: 1, isRunning: true, cancelled: false, error: false, read: 25, total: 25,
                                   stages: stages(sort: (31, 86), decide: (0, nil)))
        XCTAssertEqual(pips[1], .active(fill: 31.0 / 86.0))
        let unknown = stageStripState(stage: 1, isRunning: true, cancelled: false, error: false, read: 25, total: 25,
                                      stages: stages(sort: (3, nil), decide: (0, nil)))
        XCTAssertEqual(unknown[1], .active(fill: nil), "no total, no fraction")
    }

    func test_noticeAndFileNeverCarryAFraction() {
        for stage in [3, 4] {
            let pips = stageStripState(stage: stage, isRunning: true, cancelled: false, error: false, read: 25,
                                       total: 25, stages: stages(sort: (86, 86), decide: (12, 12)))
            XCTAssertEqual(pips[stage], .active(fill: nil))
        }
    }

    func test_captionsPerStage() throws {
        var d = try JSONDecoder().decode(SleepDrainInfo.self, from: Data(#"{"frozen":287,"active":true}"#.utf8))
        d.batchState = .init(index: 3, of: 12, total: 25, read: 24, reading: 0, failed: 1)
        d.stages = stages(sort: (0, nil), decide: (0, 12))
        XCTAssertEqual(stageCaption(drain: d, activeStage: 1, locale: V5Fixture.en)?.text, "Reading conversations")
        XCTAssertEqual(stageCaption(drain: d, activeStage: 1, locale: V5Fixture.en)?.failed,
                       "1 could not be read, it gets one more try")
        XCTAssertEqual(stageCaption(drain: d, activeStage: 2, locale: V5Fixture.en)?.text,
                       "Sorting names · 24 read, 1 could not be read")
        XCTAssertEqual(stageCaption(drain: d, activeStage: 3, locale: V5Fixture.en)?.text, "Deciding · 12 pages to update")
        XCTAssertEqual(stageCaption(drain: d, activeStage: 5, locale: V5Fixture.en)?.text, "Filing. It cannot be stopped now.")
    }
}

// MARK: - Details

final class SleepV5DetailsTests: XCTestCase {
    func test_aSourceLineLeavesOutItsZeroTerms() {
        XCTAssertEqual(Copy.SleepV5.sourceLine(filed: 50, read: 14, waiting: 53, couldNotBeRead: 1, parked: 0,
                                               V5Fixture.en), "50 filed · 14 read · 53 waiting · 1 could not be read")
        XCTAssertEqual(Copy.SleepV5.sourceLine(filed: 7, read: 0, waiting: 0, couldNotBeRead: 0, parked: 0,
                                               V5Fixture.en), "7 filed")
        let lines = RunSourceLine.lines(["a": .init(frozen: 3, filed: 3), "b": .init(frozen: 5, waiting: 5)],
                                        locale: V5Fixture.en)
        XCTAssertEqual(lines.map(\.origin), ["b", "a"], "largest pile first")
    }

    func test_parkedConversationsGetARow() {
        let rows = LastCycleRow.runRows(drain: nil, paused: nil, run: nil, detail: nil, parkedCount: 2,
                                        runBilling: nil, reserveValue: nil, locale: V5Fixture.en)
        XCTAssertEqual(rows.map(\.kind), [.parked])
        XCTAssertTrue(rows[0].needsYou)
        XCTAssertEqual(rows[0].text, "2 conversations failed twice and wait for you. Retry reads them again.")
    }

    func test_aReservePauseSaysWhatWasKeptAndWhereTheLineIsSet() throws {
        let status = try V5Fixture.paused("reserve")
        let rows = LastCycleRow.runRows(drain: status.drain, paused: status.paused, run: nil, detail: nil,
                                        parkedCount: 0, runBilling: nil,
                                        reserveValue: "10% of the 5-hour window", locale: V5Fixture.en)
        XCTAssertTrue(rows.contains { $0.kind == .paused && $0.title == "Paused to leave room in your plan" })
        XCTAssertTrue(rows.contains { $0.kind == .reserve
            && $0.text == "Keep plan free is 10% of the 5-hour window, set in the engine menu." })
    }

    func test_aScheduledRunOnAKeySaysCicadaSetsNoLimit() throws {
        var drain = try XCTUnwrap(V5Fixture.drain("finished").drain)
        drain.startedBy = "schedule"
        let rows = LastCycleRow.runRows(drain: drain, paused: nil, run: nil, detail: nil, parkedCount: 0,
                                        runBilling: "charged", reserveValue: nil, locale: V5Fixture.en)
        XCTAssertTrue(rows.contains { $0.kind == .scheduled && $0.text.contains("Cicada sets no limit") })
        let local = LastCycleRow.runRows(drain: drain, paused: nil, run: nil, detail: nil, parkedCount: 0,
                                         runBilling: "local", reserveValue: nil, locale: V5Fixture.en)
        XCTAssertFalse(local.contains { $0.kind == .scheduled })
    }

    func test_theRunsRowsReplaceThePreV5DrainRows() throws {
        let status = try V5Fixture.paused("plan_window")
        let legacy = LastCycleRow.rows(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                       status: status, usageLine: "cost", drain: status.drain)
        let run = LastCycleRow.runRows(drain: status.drain, paused: status.paused, run: nil, detail: nil,
                                       parkedCount: 0, runBilling: nil, reserveValue: nil)
        let merged = LastCycleRow.merged(legacy: legacy, run: run)
        XCTAssertEqual(Set(merged.map(\.id)).count, merged.count, "one row per fact — unique ids")
        XCTAssertEqual(merged.last?.kind, .usage, "the cost stays, last")
        XCTAssertEqual(LastCycleRow.merged(legacy: legacy, run: []), legacy, "an older backend keeps its rows")
    }

    /// Final review: the continue-after-reset switch shows only for a plan, and a plan whose windows the backend
    /// can't classify says so instead of promising a continue that never arms.
    func test_theContinueSwitchShowsOnlyWhereItCanArmOrSaysWhyNot() {
        func p(_ engine: String, _ billing: String?) -> SleepEnginePreview {
            SleepEnginePreview(engine: engine, model: "m", why: "", billing: billing)
        }
        XCTAssertEqual(ContinueAfterResetRow.caption(for: p("claude-cli", "plan")), Copy.SleepV5.continueAfterResetCaption)
        XCTAssertEqual(ContinueAfterResetRow.caption(for: p("codex-cli", "plan")),
                       Copy.SleepV5.continueAfterResetUnavailableCaption)
        XCTAssertNil(ContinueAfterResetRow.caption(for: p("litellm", "charged")))
        XCTAssertNil(ContinueAfterResetRow.caption(for: p("ollama", "local")))
        XCTAssertNil(ContinueAfterResetRow.caption(for: nil))
    }

    /// Final review: a switch that was on but did not fire says why in the paused row — every blocked reason the
    /// backend can arm-and-fail on has words, none names a provider, and the never-arming ones stay silent.
    func test_aBlockedAutoContinueIsSaidInWords() {
        for reason in ["weekly", "unknown_limit", "no_reset_time", "used_twice", "too_far", "no_scheduler", "off",
                       "bank_changed", "busy", "engine_changed"] {
            let words = Copy.SleepV5.autoContinueBlocked(reason)
            XCTAssertNotNil(words, reason)
            for word in V5Fixture.providerWords { XCTAssertFalse(words?.contains(word) ?? false, word) }
        }
        for reason in ["scheduled", "reason", nil] as [String?] { XCTAssertNil(Copy.SleepV5.autoContinueBlocked(reason)) }
        XCTAssertFalse(Copy.SleepV5.continueAfterResetUnavailableCaption.contains("ChatGPT"))
    }

    /// Review fix — `POST /sleep/parked/retry` answers 409 while a run reads or waits paused, so Retry (the queue
    /// rows' and Last cycle's) is offered only when neither is true.
    func test_retryIsAbsentWhileARunReadsOrWaitsPaused() {
        XCTAssertTrue(LastCycleRow.canRetryParked(isRunning: false, isPaused: false))
        XCTAssertFalse(LastCycleRow.canRetryParked(isRunning: true, isPaused: false))
        XCTAssertFalse(LastCycleRow.canRetryParked(isRunning: false, isPaused: true))
        XCTAssertFalse(LastCycleRow.canRetryParked(isRunning: true, isPaused: true))
        XCTAssertTrue(Copy.SleepV5.retryAfterRun.contains("Continue or end this run first"))
    }

    /// Review fix — the What's waiting block's Retry is optional, and the Details pass it only through the gate.
    func test_detailsPassRetryOnlyThroughTheGate() throws {
        let details = try String(contentsOf: XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.lastPathComponent == "SleepDetails.swift" }), encoding: .utf8)
        XCTAssertTrue(details.contains("onRetryParked: canRetry ? { onRetryParked(nil) } : nil"))
        XCTAssertTrue(details.contains("onRetry: canRetry ? onRetryParked : nil"))
    }

    /// Review fix — the scheduled note has its own title (never the run's state) and reads how THIS run was billed.
    func test_theScheduledNoteHasItsOwnTitleAndTheRunsOwnBilling() throws {
        var drain = try XCTUnwrap(V5Fixture.drain("finished").drain)
        drain.startedBy = "schedule"
        let rows = LastCycleRow.runRows(drain: drain, paused: nil, run: nil, detail: nil, parkedCount: 0,
                                        runBilling: "charged", reserveValue: nil, locale: V5Fixture.en)
        let note = try XCTUnwrap(rows.first { $0.kind == .scheduled })
        XCTAssertEqual(note.title, "Started on its schedule")
        XCTAssertNotEqual(note.title, Copy.SleepV5.runLiveTitle)
        func usage(_ json: String) throws -> CycleUsage { try JSONDecoder().decode(CycleUsage.self, from: Data(json.utf8)) }
        XCTAssertEqual(LastCycleRow.runBilling(usage: try usage(#"{"basis":"charged"}"#), summary: nil), "charged")
        XCTAssertEqual(LastCycleRow.runBilling(usage: try usage(#"{"basis":"list"}"#), summary: nil), "charged")
        XCTAssertEqual(LastCycleRow.runBilling(usage: try usage(#"{"basis":"free"}"#), summary: nil), "local")
        XCTAssertNil(LastCycleRow.runBilling(usage: try usage(#"{"basis":"plan"}"#), summary: nil))
        XCTAssertEqual(LastCycleRow.runBilling(
            usage: try usage(#"{"basis":"mixed","models":[{"basis":"free"},{"basis":"charged"}]}"#), summary: nil),
            "charged")
        let summary = try JSONDecoder().decode(CycleUsageSummary.self, from: Data(#"{"basis":"free"}"#.utf8))
        XCTAssertEqual(LastCycleRow.runBilling(usage: nil, summary: summary), "local")
        XCTAssertNil(LastCycleRow.runBilling(usage: nil, summary: nil), "nothing measured — no note, never a guess")
    }

    /// Review fix — a touched page reads as its name; an id the graph does not hold stays verbatim.
    func test_aTouchedPageReadsAsItsName() {
        let names = EntityNames(byId: ["alpha-project": "Alpha Project"])
        XCTAssertEqual(RunDetailBlock.pageLabel("alpha-project", names: names), "Alpha Project")
        XCTAssertEqual(RunDetailBlock.pageLabel("bob-example", names: names), "bob-example")
    }

    /// Review fix — a run's detail is refetched whenever its numbers, its pause or its end move.
    func test_theRunDetailKeyMovesWithTheRun() throws {
        let paused = try V5Fixture.paused("user")
        let a = SleepViewModel.runDetailFreshness(drain: paused.drain, paused: paused.paused)
        XCTAssertEqual(a, SleepViewModel.runDetailFreshness(drain: paused.drain, paused: paused.paused))
        XCTAssertNotEqual(a, SleepViewModel.runDetailFreshness(drain: paused.drain, paused: nil), "Continue moves it")
        var more = try XCTUnwrap(paused.drain)
        more.filed += 1
        XCTAssertNotEqual(a, SleepViewModel.runDetailFreshness(drain: more, paused: paused.paused))
        var done = try XCTUnwrap(paused.drain)
        done.finished = true
        XCTAssertNotEqual(a, SleepViewModel.runDetailFreshness(drain: done, paused: nil), "the end moves it")
    }

    func test_aQueueRowSaysWhereItStandsInWords() {
        XCTAssertEqual(Copy.SleepV5.queueStateWords(state: "could_not_be_read", reason: "empty_answer", attempts: 1),
                       "could not be read · the answer came back empty · it gets one more try")
        XCTAssertEqual(Copy.SleepV5.queueStateWords(state: "parked", reason: "empty_answer", attempts: 2),
                       "the answer came back empty twice")
    }
}

// MARK: - Past nights

final class SleepV5RunDetailTests: XCTestCase {
    private func entry(_ hash: String, drain: String? = nil, run: String? = nil) -> String {
        var s = #"{"commitHash":"\#(hash)","date":"2026-09-30T10:14:00+00:00","message":"m","filesChanged":[],"kind":"sleep","entitiesCreated":1,"entitiesUpdated":2,"episodes":25,"sessions":1,"authors":[]"#
        if let drain { s += #","drainId":"\#(drain)","batch":1,"batches":12"# }
        if let run { s += #","run":\#(run)"# }
        return s + "}"
    }

    private let run = #"{"id":"sleep_r1","batches":12,"filed":286,"parked":1,"frozen":287,"pauses":1,"readMs":8040000,"pausedMs":16620000,"startedAt":"2026-09-30T10:14:00+00:00","state":"finished"}"#

    func test_aRunsBatchesFoldIntoOneRowWithTheServersNumbers() throws {
        let entries = try V5Fixture.entries("[" + [entry("c3", drain: "sleep_r1", run: run), entry("plain"),
                                                   entry("c2", drain: "sleep_r1", run: run),
                                                   entry("c1", drain: "sleep_r1", run: run)].joined(separator: ",") + "]")
        let items = PastNightItem.group(entries)
        XCTAssertEqual(items.count, 2)
        guard case .run(let ref, let members) = items[0] else { return XCTFail("the run leads, where its newest batch was") }
        XCTAssertEqual(members.map(\.commitHash), ["c3", "c2", "c1"])
        XCTAssertEqual(RunPresentation.title(ref, locale: V5Fixture.en),
                       "Reading all · 286 conversations · 12 batches · 1 pause",
                       "from the run's own summary, never summed from three visible rows")
        XCTAssertEqual(RunPresentation.times(ref, locale: V5Fixture.en),
                       "Read for 2 h 14 m, paused 4 h 37 m. 1 conversation could not be read.")
    }

    func test_anEntryWithoutARunSummaryStaysARowOfItsOwn() throws {
        let entries = try V5Fixture.entries("[" + entry("x", drain: "sleep_r1") + "," + entry("y") + "]")
        XCTAssertEqual(PastNightItem.group(entries).map(\.id), ["x", "y"])
    }

    func test_aPartialBatchAndAPauseRow() {
        XCTAssertEqual(RunPresentation.batchLine(.init(index: 5, filed: 9, notFiled: 16), locale: V5Fixture.en),
                       "Batch 5 · 9 filed · 16 not filed")
        let pause = SleepRunDetail.Pause(startedAt: "2026-09-30T11:04:00+00:00", endedAt: "2026-09-30T15:41:00+00:00",
                                         reason: "reserve")
        XCTAssertEqual(RunPresentation.pauseLine(pause, timeZone: V5Fixture.utc),
                       "Paused 11:04 AM to 3:41 PM · to leave room in your plan")
    }

    func test_theRunDetailFixtureListsItsModelsStagesAsData() throws {
        let detail = try V5Fixture.decode(SleepRunDetail.self, "sleep-run-detail.json")
        XCTAssertFalse(CycleUsageText.detailLines(detail.usage).models.isEmpty
                       && CycleUsageText.detailLines(detail.usage).empty == nil && detail.usage != nil,
                       "sanity: the usage shape is the per-cycle one")
        XCTAssertEqual(Copy.SleepV5.stageWord("extraction"), "Read")
        XCTAssertNil(Copy.SleepV5.stageWord("made-up"), "never a guess")
    }
}

// MARK: - Doors

final class SleepV5DoorsTests: XCTestCase {
    func test_theMenuBarSaysAllAndNeverContinues() {
        let idle = SleepDoor(paused: nil, readable: 287, batchSize: 25)
        XCTAssertEqual(idle.menuItemTitle, "Consolidate now — all 287")
        XCTAssertNil(idle.menuHeader)
        let paused = SleepDoor(paused: (98, 287), readable: 189, batchSize: 25)
        XCTAssertEqual(paused.menuItemTitle, "Continue on the Sleep page…")
        XCTAssertEqual(paused.menuHeader, "Paused — 98 of 287 filed")
    }

    /// Review fix — a pause whose record has not loaded (the Sleep page never opened) says "Paused", never
    /// "0 of 0 filed"; an unknown batch size is left out of the caption, never the fallback 25.
    func test_aDoorNeverFormatsAnUnknownCount() {
        let unknown = SleepDoor(paused: nil, readable: 12, batchSize: nil, pausedCountsUnknown: true)
        XCTAssertTrue(unknown.isPaused)
        XCTAssertEqual(unknown.menuHeader, "Paused")
        XCTAssertEqual(unknown.menuItemTitle, "Continue on the Sleep page…")
        XCTAssertEqual(SleepDoor(paused: nil, readable: 318, batchSize: nil).readNowCaption,
                       "Reads all 318 waiting, oldest first. Follow along on the Sleep page.")
        XCTAssertEqual(SleepDoor(paused: nil, readable: 318, batchSize: 10).readNowCaption,
                       "Reads all 318 waiting, oldest first, saving every 10. Follow along on the Sleep page.")
    }

    func test_readNowSaysWhatItReads() {
        XCTAssertEqual(SleepDoor(paused: nil, readable: 318, batchSize: 25).readNowCaption,
                       "Reads all 318 waiting, oldest first, saving every 25. Follow along on the Sleep page.")
        XCTAssertEqual(SleepDoor(paused: (1, 9), readable: 8, batchSize: 25).readNowCaption,
                       "A run is paused. Continue it on the Sleep page.")
        XCTAssertNil(SleepDoor(paused: nil, readable: 0, batchSize: 25).readNowCaption)
    }

    /// M7 — every "all N" counts what a run would read: waiting minus parked.
    func test_captionExcludesParked() throws {
        let body = #"{"unprocessedCount":10,"parkedCount":3,"hasRunBefore":true,"volumePct":0,"agePct":0}"#
        let debt = try JSONDecoder().decode(SleepDebtInfo.self, from: Data(body.utf8))
        XCTAssertEqual(debt.readable, 7)
        XCTAssertEqual(SleepDoor(paused: nil, readable: debt.readable, batchSize: 25).menuItemTitle,
                       "Consolidate now — all 7")
    }

    /// Only the Sleep page's Continue resumes a paused run: one call site passes `continueRun: true`, and every door
    /// goes through `triggerManually`, which routes to the page while a run is paused.
    func test_onlyTheSleepPageContinues() throws {
        var callers: [String] = []
        for file in try ThemeTokenTests.swiftSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            if text.contains("TriggerSleep(continueRun: true)") { callers.append(file.lastPathComponent) }
        }
        XCTAssertEqual(callers, ["SleepViewModel.swift"])
        let vm = try String(contentsOf: XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.lastPathComponent == "SleepViewModel.swift" }), encoding: .utf8)
        let trigger = try XCTUnwrap(vm.range(of: "func triggerManually()"))
        let body = vm[trigger.upperBound...].prefix(600)
        XCTAssertTrue(body.contains("if isPaused"), "the paused check sits inside the one choke point (M8)")
        XCTAssertTrue(body.contains("onPausedDoor?()"))
    }

    func test_theMenuBarTitleLivesInCopy() throws {
        let menu = try String(contentsOf: XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.lastPathComponent == "MenuBarManager.swift" }), encoding: .utf8)
        XCTAssertFalse(menu.contains("\"Run sleep cycle now\""))
    }
}

// MARK: - Reading options

final class SleepV5ReadingOptionsTests: XCTestCase {
    /// The sheet's code, without its comments (whose doc says what is left out, on purpose).
    private func sheetSource() throws -> String {
        try String(contentsOf: XCTUnwrap(SleepNumbersLintTests.sleepSources().first {
            $0.lastPathComponent == "ReadingOptionsSheet.swift" }), encoding: .utf8)
            .components(separatedBy: .newlines)
            .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
            .joined(separator: "\n")
    }

    func test_defaultsAreTheOwnersDecisions() {
        let options = SleepRunOptions()
        XCTAssertEqual(options.batchSizeChoices, [10, 25, 50])
        XCTAssertFalse(options.continueAfterReset, "ruling 15: opt-in, off")
        XCTAssertNil(options.reservePct, "decision 4: off")
    }

    /// Decision 3 (owner, 2026-09-30): "Read faster" is not built.
    func test_theSheetHasNoReadFasterAndNoAdvice() throws {
        let sheet = try sheetSource()
        for banned in ["Read faster", "At once", "Reading model", "first batch", "API key or OpenRouter"] {
            XCTAssertFalse(sheet.contains(banned), banned)
        }
        for word in V5Fixture.providerWords { XCTAssertFalse(Copy.SleepV5.optionsNote.contains(word), word) }
        XCTAssertTrue(Copy.SleepV5.optionsNote.contains("the engine you chose"))
    }

    func test_eachControlWritesOnChange() throws {
        let sheet = try sheetSource()
        XCTAssertTrue(sheet.contains("updateRunOptions(.batchSize("))
        XCTAssertTrue(sheet.contains("updateRunOptions(.continueAfterReset("))
    }

    func test_theIntroAndSavesCount() {
        XCTAssertEqual(ReadingOptionsSheet.saves(waiting: 287, batchSize: 25), 12)
        XCTAssertEqual(Copy.SleepV5.savesFor(saves: 12, waiting: 287, V5Fixture.en), "12 saves for 287 conversations.")
    }
}

// MARK: - Engine menu

final class SleepV5EngineMenuTests: XCTestCase {
    func test_keepPlanFreeIsOfferedOnlyForAPlan() {
        let status = SleepReserveStatus(pct: 10, choices: [5, 10, 20, 30], applies: false,
                                        windows: [.init(window: "five_hour", enforced: true)])
        XCTAssertNil(EngineQuickMenuModel.Reserve.from(status, billing: "charged"))
        XCTAssertNotNil(EngineQuickMenuModel.Reserve.from(status, billing: "plan"))
        XCTAssertNil(EngineQuickMenuModel.Reserve.from(nil, billing: "plan"), "an older backend offers nothing")
    }

    func test_anUnreportedWindowIsSaidOnlyWhenTheWireSaysSo() {
        let status = SleepReserveStatus(pct: 10, choices: [], applies: true,
                                        windows: [.init(window: "five_hour", enforced: true),
                                                  .init(window: "weekly", enforced: false, reason: "not_reported"),
                                                  .init(window: "seven_day", enforced: nil)])
        let reserve = EngineQuickMenuModel.Reserve.from(status, billing: "plan")
        XCTAssertEqual(reserve?.notReported.count, 1)
        XCTAssertEqual(reserve?.choices, [5, 10, 20, 30])
        let off = EngineQuickMenuModel.Reserve.from(SleepReserveStatus(pct: nil, applies: true, windows: status.windows),
                                                    billing: "plan")
        XCTAssertEqual(off?.value, "Off")
        XCTAssertEqual(off?.notReported, [], "nothing to promise or deny while off")
    }

    func test_scheduledSpendFollowsBilling() {
        XCTAssertTrue(Copy.SleepV5.scheduledSpend("charged")?.contains("Cicada sets no limit") == true)
        XCTAssertEqual(Copy.SleepV5.scheduledSpend("local"), "It reads everything waiting, on this Mac.")
        XCTAssertNil(Copy.SleepV5.scheduledSpend("plan"), "a scheduled run never uses a plan (ruling 4)")
        XCTAssertNil(Copy.SleepV5.scheduledSpend(nil))
    }
}

// MARK: - Lints

/// Owner, 2026-09-30: never name a provider or a model as the one doing a job. A name appears only where it is the
/// person's own current choice, which arrives as data — so no string literal under the Sleep page's own files, the
/// intake card or the v5 copy may spell one, outside the files that render the person's choice.
final class SleepProviderNeutralLintTests: XCTestCase {
    /// Files that render the person's own engine, model or a cycle's usage rows — names arrive as data there.
    /// `RoomFeed.swift` names the app whose own session folder the person just dropped (a refusal that says which
    /// folder it was), never a provider doing Sleep's job.
    static let allowed = ["EngineQuickMenu.swift", "EngineChooser.swift", "SleepDetails.swift", "CycleUsageText.swift",
                          "ModelNames.swift", "RoomFeed.swift"]

    func test_theV5CopyNamesNoProvider() {
        for sentence in Copy.sleepV5Sentences + Copy.sleepV5Labels {
            for word in V5Fixture.providerWords {
                XCTAssertFalse(sentence.range(of: "\\b\(word)\\b", options: .regularExpression) != nil,
                               "\(sentence) names \(word)")
            }
        }
    }

    func test_noLiteralUnderSleepOrIntakeNamesAProvider() throws {
        let files = try ThemeTokenTests.swiftSources().filter {
            ($0.path.contains("/Views/Sleep/") || $0.path.contains("/Views/Intake/")
                || $0.lastPathComponent == "Copy+SleepV5.swift")
                && !Self.allowed.contains($0.lastPathComponent)
        }
        XCTAssertFalse(files.isEmpty)
        let literal = try NSRegularExpression(pattern: #""([^"\\]|\\.)*""#)
        var offenders: [String] = []
        for file in files {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//"), !code.hasPrefix("///") else { continue }
                for match in literal.matches(in: line, range: NSRange(line.startIndex..., in: line)) {
                    let s = (line as NSString).substring(with: match.range)
                    for word in V5Fixture.providerWords
                    where s.range(of: "\\b\(word)\\b", options: .regularExpression) != nil {
                        offenders.append("\(file.lastPathComponent):\(index + 1) \(word)")
                    }
                }
            }
        }
        XCTAssertEqual(offenders, [], "describe the step (\"the engine you chose\"), never a provider")
    }
}

/// Ruling 12 (spec 5.3: this suite did not exist yet) — a price, a token count or a plan window's percentage is said
/// only in Details and the engine menu, through `CycleUsageText`. Under Views/Sleep a `$` or "tokens" literal may appear
/// only in the allowed files; the v5 copy's one percentage (the reserve) is rendered only by them.
final class PriceLintTests: XCTestCase {
    static let allowed = ["EngineQuickMenu.swift", "SleepDetails.swift", "CycleUsageText.swift"]

    func test_pricesAndTokensLiveInDetailsAndTheEngineMenuOnly() throws {
        let files = try ThemeTokenTests.swiftSources().filter {
            $0.path.contains("/Views/Sleep/") && !Self.allowed.contains($0.lastPathComponent)
        }
        var offenders: [String] = []
        for file in files {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                if code.contains("\"$") || code.contains("$\\(") || code.range(of: #""[^"]*\btokens\b"#,
                                                                                 options: .regularExpression) != nil {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [])
    }

    func test_theReservesPercentageIsRenderedOnlyByTheEngineMenuAndDetails() throws {
        var renderers: [String] = []
        for file in try ThemeTokenTests.swiftSources() where file.lastPathComponent != "Copy+SleepV5.swift" {
            let text = try String(contentsOf: file, encoding: .utf8)
            if text.contains("SleepV5.reserveValue(") || text.contains("SleepV5.reserveChoice(")
                || text.contains("SleepV5.keepPlanFreeIs(") {
                renderers.append(file.lastPathComponent)
            }
        }
        XCTAssertEqual(Set(renderers), ["EngineQuickMenu.swift", "SleepRunDetails.swift"])
    }
}
