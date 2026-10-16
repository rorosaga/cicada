import XCTest
@testable import CicadaApp

/// Live report (2026-10-16): after a 78-minute scheduled drain on a metered engine and then a 24-minute person-started
/// drain on the Claude plan, Details still showed one batch's charge ("What it cost: 0,03 US$ charged · OpenRouter"),
/// one batch's time ("Last cycle took 3 m 49 s") and a dash for the engine read from a status fetched before either
/// run. All three now come from one record — the newest finished cycle in history — and a drain is one cycle.
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

    func testThePlanDrainAfterTheScheduledOneIsTheLastCycleWholeAndPriceless() throws {
        let h = try history([
            row("p6", engine: "claude-cli", batchCost: planBatch, drain: "plan-run",
                run: runRef("plan-run", readMs: 1_440_000, state: "finished", cost: planRun)),
            row("m35", engine: "litellm", batchCost: meteredBatch, drain: "sched-run",
                run: runRef("sched-run", readMs: 4_680_000, state: "finished", cost: meteredRun)),
        ])
        let f = try XCTUnwrap(LastCycleFigures.latest(h))
        XCTAssertEqual(f.durationMs, 1_440_000, "the run's own time, not its last batch's 3 m 49 s")
        XCTAssertEqual(f.engine, "claude-cli", "from the commits, never a status read before the run")
        XCTAssertFalse(f.isOneBatch)
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

    func testAMeteredDrainShowsTheWholeRunsChargeWithItsBasis() throws {
        let h = try history([row("m35", engine: "litellm", batchCost: meteredBatch, drain: "sched-run",
                                 run: runRef("sched-run", readMs: 4_680_000, state: "finished", cost: meteredRun))])
        let f = try XCTUnwrap(LastCycleFigures.latest(h))
        XCTAssertEqual(f.durationMs, 4_680_000)
        let line = try XCTUnwrap(CycleUsageText.lastCycleLine(f.usage, locale: en))
        XCTAssertTrue(line.contains("1.42") && line.contains("charged") && line.contains("OpenRouter"), line)
        XCTAssertFalse(line.contains("0.03"), "never the last batch's charge: \(line)")
    }

    func testARunStillReadingOrPausedIsNotTheLastCycle() throws {
        for state in ["running", "paused"] {
            let h = try history([
                row("r2", engine: "claude-cli", batchCost: planBatch, drain: "live",
                    run: runRef("live", readMs: 60_000, state: state, cost: planRun)),
                row("m35", engine: "litellm", batchCost: meteredBatch, drain: "sched-run",
                    run: runRef("sched-run", readMs: 4_680_000, state: "finished", cost: meteredRun)),
            ])
            let f = try XCTUnwrap(LastCycleFigures.latest(h))
            XCTAssertEqual(f.durationMs, 4_680_000, state)
            XCTAssertEqual(f.engine, "litellm", state)
        }
        let onlyLive = try history([row("r2", engine: "claude-cli", batchCost: planBatch, drain: "live",
                                        run: runRef("live", readMs: 60_000, state: "paused", cost: planRun))])
        XCTAssertNil(LastCycleFigures.latest(onlyLive))
        let rows = readoutRows(entityCount: 1, sourceCount: 1, lastDurationMs: nil, lastEngine: nil, engineDetail: nil,
                               hasFinishedCycle: false, locale: en)
        XCTAssertEqual(rows.first { $0.id == "lastCycle" }?.reason, Copy.SleepDetailsWords.noFinishedCycle)
        XCTAssertEqual(rows.first { $0.id == "engine" }?.reason, Copy.SleepDetailsWords.noFinishedCycle)
    }

    func testABatchWhoseRunSummaryIsMissingFallsBackToItsOwnFiguresAndSaysSo() throws {
        let h = try history([row("b3", engine: "litellm", batchCost: meteredBatch, drain: "lost")])
        let f = try XCTUnwrap(LastCycleFigures.latest(h))
        XCTAssertEqual(f.durationMs, 229_000)
        XCTAssertTrue(f.isOneBatch)
        XCTAssertEqual(f.usage?.costUsd, 0.03)
    }

    func testAPlainCycleIsItsOwnRecordAndAnInboxCommitIsNever() throws {
        let inbox = #"{"commitHash":"i1","date":"2026-10-16T10:00:00+00:00","message":"Inbox resolution","filesChanged":[],"kind":"inbox"}"#
        let h = try history([inbox, row("c1", engine: "ollama", batchCost: #"{"basis":"free","engine":"ollama"}"#)])
        let f = try XCTUnwrap(LastCycleFigures.latest(h))
        XCTAssertEqual(f.engine, "ollama")
        XCTAssertEqual(f.durationMs, 229_000)
        XCTAssertEqual(CycleUsageText.lastCycleLine(f.usage, locale: en), Copy.SleepUsage.ranLocally)
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
