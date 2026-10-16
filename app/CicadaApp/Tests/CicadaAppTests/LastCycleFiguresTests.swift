import XCTest
@testable import CicadaApp

/// Live report (2026-10-16): after a 78-minute scheduled drain on a metered engine and then a 24-minute person-started
/// drain on the Claude plan, Details still showed one batch's charge ("What it cost: 0,03 US$ charged · OpenRouter"),
/// one batch's time ("Last cycle took 3 m 49 s") and a dash for the engine read from a status fetched before either
/// run. All three now come from one record — the newest finished cycle, which the backend finds — and a drain is one
/// cycle.
final class LastCycleFiguresTests: XCTestCase {
    private let en = Locale(identifier: "en_US")

    /// One history row, as `GET /sleep/history` sends it.
    private func row(_ hash: String, engine: String?, batchCost: String, drain: String? = nil,
                     run: String? = nil, batches: Int = 3, durationMs: Int = 229_000) -> String {
        var s = #"{"commitHash":"\#(hash)","date":"2026-10-16T09:00:00+00:00","message":"Sleep cycle","filesChanged":[],"#
            + #""kind":"sleep","episodes":25,"durationMs":\#(durationMs),"usageSummary":\#(batchCost)"#
        if let engine { s += #","engine":"\#(engine)""# }
        if let drain { s += #","drainId":"\#(drain)","batch":\#(batches),"batches":\#(batches)"# }
        if let run { s += #","run":\#(run)"# }
        return s + "}"
    }

    private func runRef(_ id: String, readMs: Int, state: String, cost: String?) -> String {
        var s = #"{"id":"\#(id)","batches":6,"filed":150,"frozen":150,"readMs":\#(readMs),"state":"\#(state)","#
            + #""startedBy":"user""#
        if let cost { s += #","usageSummary":\#(cost)"# }
        return s + "}"
    }

    private let meteredBatch = #"{"basis":"charged","costUsd":0.03,"engine":"litellm","connection":"byok-openrouter"}"#
    private let meteredRun = #"{"basis":"charged","costUsd":1.42,"engine":"litellm","connection":"byok-openrouter"}"#
    private let planBatch = #"{"basis":"list","equivCostUsd":0.8,"engine":"claude-cli","connection":"claude-plan","plan":{"window":"five_hour","before":0.10,"after":0.14}}"#
    private let planRun = #"{"basis":"list","equivCostUsd":4.2,"engine":"claude-cli","connection":"claude-plan","plan":{"window":"five_hour","before":0.10,"after":0.31}}"#

    private func history(_ rows: [String]) throws -> [SleepHistoryEntry] {
        try JSONDecoder().decode([SleepHistoryEntry].self, from: Data(("[" + rows.joined(separator: ",") + "]").utf8))
    }

    /// `GET /sleep/status` with the backend's `lastFinishedCycle` (or `null`, or no key at all from an older backend).
    private func status(_ state: String = "idle", lastFinished: String?) throws -> SleepStatusResponse {
        var s = #"{"status":"\#(state)""#
        if let lastFinished { s += #","lastFinishedCycle":\#(lastFinished)"# }
        return try JSONDecoder().decode(SleepStatusResponse.self, from: Data((s + "}").utf8))
    }

    private func finished(drain: String, ms: Int, engine: String, cost: String) -> String {
        #"{"commitHash":"c-\#(drain)","date":"2026-10-16T09:00:00+00:00","drainId":"\#(drain)","batches":35,"#
            + #""durationMs":\#(ms),"engine":"\#(engine)","usageSummary":\#(cost),"state":"finished"}"#
    }

    /// The review blocker: a 20-batch drain still reading, or paused on Continue, fills all 15 rows the app holds.
    /// Details shows the finished run before it — the backend found it — never "No finished cycle".
    func testALiveTwentyBatchDrainShowsTheFinishedRunBeforeIt() throws {
        let live = try history((1...15).reversed().map {
            row("p\($0)", engine: "claude-cli", batchCost: planBatch, drain: "plan-run",
                run: runRef("plan-run", readMs: 900_000, state: "running", cost: nil), batches: 20)
        })
        for state in ["running", "idle"] {   // reading, or paused (a paused run leaves Sleep idle)
            let f = try XCTUnwrap(LastCycleFigures.resolve(
                status: try status(state, lastFinished: finished(drain: "sched-run", ms: 4_680_000, engine: "litellm",
                                                                 cost: meteredRun)),
                history: live), state)
            XCTAssertEqual(f.durationMs, 4_680_000, "the run's own time, not a batch's 3 m 49 s")
            XCTAssertEqual(f.engine, "litellm")
            XCTAssertFalse(f.isOneBatch)
            let line = try XCTUnwrap(CycleUsageText.lastCycleLine(f.usage, locale: en))
            XCTAssertTrue(line.contains("1.42") && line.contains("charged") && line.contains("OpenRouter"), line)
            XCTAssertFalse(line.contains("0.03"), "never the last batch's charge: \(line)")
        }
    }

    func testAFinishedPlanRunIsTheLastCycleWholeAndPriceless() throws {
        let f = try XCTUnwrap(LastCycleFigures.resolve(
            status: try status(lastFinished: finished(drain: "plan-run", ms: 1_440_000, engine: "claude-cli",
                                                      cost: planRun)),
            history: []))
        XCTAssertEqual(f.engine, "claude-cli")
        let line = try XCTUnwrap(CycleUsageText.lastCycleLine(f.usage, locale: en))
        XCTAssertTrue(line.hasPrefix("Claude plan"), line)
        XCTAssertTrue(line.contains("31%"), "the run's window, first batch to last: \(line)")
        XCTAssertFalse(line.contains("$"), "a plan run shows no price: \(line)")
        let rows = readoutRows(entityCount: 1, sourceCount: 1, lastDurationMs: f.durationMs, lastEngine: f.engine,
                               engineDetail: nil, lastIsOneBatch: f.isOneBatch, locale: en)
        XCTAssertEqual(rows.first { $0.id == "lastCycle" }?.key, Copy.SleepDetailsWords.lastCycleTook)
        XCTAssertEqual(rows.first { $0.id == "lastCycle" }?.value, "24 m")
        XCTAssertEqual(rows.first { $0.id == "engine" }?.value, Copy.engineLabel("claude-cli"))
    }

    /// `null` is the backend saying there is none; only then does the dash say so.
    func testNoFinishedCycleOnlyWhenTheBackendSaysSo() throws {
        let live = try history([row("p1", engine: "claude-cli", batchCost: planBatch, drain: "plan-run",
                                    run: runRef("plan-run", readMs: 60_000, state: "paused", cost: nil))])
        XCTAssertNil(LastCycleFigures.resolve(status: try status(lastFinished: "null"), history: live))
        let rows = readoutRows(entityCount: 1, sourceCount: 1, lastDurationMs: nil, lastEngine: nil, engineDetail: nil,
                               hasFinishedCycle: false, locale: en)
        XCTAssertEqual(rows.first { $0.id == "lastCycle" }?.reason, Copy.SleepDetailsWords.noFinishedCycle)
        XCTAssertEqual(rows.first { $0.id == "engine" }?.reason, Copy.SleepDetailsWords.noFinishedCycle)
    }

    /// An older backend sends no `lastFinishedCycle`: the newest batch's own figures, titled as one batch.
    func testAnOlderBackendFallsBackToTheNewestBatchUnderLastBatch() throws {
        let h = try history([row("b3", engine: "litellm", batchCost: meteredBatch, drain: "sched-run")])
        for s in [try status(lastFinished: nil), nil] {
            let f = try XCTUnwrap(LastCycleFigures.resolve(status: s, history: h))
            XCTAssertEqual(f.durationMs, 229_000)
            XCTAssertTrue(f.isOneBatch)
            XCTAssertEqual(f.usage?.costUsd, 0.03)
        }
        let rows = LastCycleRow.rows(pageError: nil, cancelled: false, capped: false, indexWarning: nil, status: nil,
                                     usageLine: "x", usageIsOneBatch: true, locale: en)
        XCTAssertEqual(rows.last?.title, Copy.SleepUsage.lastBatchTitle)
        let inbox = #"{"commitHash":"i1","date":"2026-10-16T10:00:00+00:00","message":"Inbox resolution","filesChanged":[],"kind":"inbox"}"#
        let plain = try XCTUnwrap(LastCycleFigures.resolve(
            status: nil, history: try history([inbox, row("c1", engine: "ollama", batchCost: #"{"basis":"free","engine":"ollama"}"#)])))
        XCTAssertEqual(plain.engine, "ollama", "an inbox commit is never the cycle")
        XCTAssertFalse(plain.isOneBatch)
        XCTAssertEqual(CycleUsageText.lastCycleLine(plain.usage, locale: en), Copy.SleepUsage.ranLocally)
    }

    /// A drain moves the Store's Sleep time every batch: the page refetches at most every 30 s while it reads, and
    /// always once it is not reading.
    func testThePageRefetchIsThrottledOnlyWhileARunReads() {
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        XCTAssertTrue(SleepPageRefresh.shouldRefetch(running: true, last: nil, now: t0))
        XCTAssertFalse(SleepPageRefresh.shouldRefetch(running: true, last: t0, now: t0.addingTimeInterval(12)))
        XCTAssertTrue(SleepPageRefresh.shouldRefetch(running: true, last: t0, now: t0.addingTimeInterval(30)))
        XCTAssertTrue(SleepPageRefresh.shouldRefetch(running: false, last: t0, now: t0.addingTimeInterval(1)),
                      "the run ending always refetches")
    }

    func testARunContinuedOnAnotherEngineKeepsItsRealChargeAndDropsTheEstimate() {
        let mixed = CycleUsageSummary(basis: "mixed", costUsd: 0.9, equivCostUsd: 3.1, engine: "claude-cli",
                                      connection: "claude-plan",
                                      plan: CycleUsageSummaryPlan(window: "five_hour", before: 0.1, after: 0.2))
        let line = CycleUsageText.lastCycleLine(mixed, locale: en) ?? ""
        XCTAssertTrue(line.contains("0.90"), line)
        XCTAssertFalse(line.contains("3.10"), "a list-price estimate beside a plan is dropped: \(line)")
    }
}
