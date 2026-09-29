import XCTest
@testable import CicadaApp

/// 2026-09-28 ruling (TODO ruling 12) — what a Sleep cycle cost, on the Sleep page's Details and its
/// engine menu. Every string is decided here from synthetic wire values; nothing reaches the network.
final class CycleUsageTextTests: XCTestCase {
    private let us = Locale(identifier: "en_US")
    private let utc = TimeZone(identifier: "UTC")!
    /// 2026-09-29 12:00 UTC.
    private let now = Date(timeIntervalSince1970: 1_790_683_200)

    /// macOS 15+ puts a narrow no-break space before "PM"; the words are the same.
    private func plain(_ s: String?) -> String? {
        s?.replacingOccurrences(of: "\u{202F}", with: " ").replacingOccurrences(of: "\u{00A0}", with: " ")
    }

    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    // MARK: Formatting

    func testCurrencyIsTwoDecimalsInTheReadersLocaleAndBelowACentSaysSo() {
        XCTAssertEqual(UsageFormat.currency(0.42, locale: us), "$0.42")
        XCTAssertEqual(UsageFormat.currency(1234.5, locale: us), "$1,234.50")
        XCTAssertEqual(UsageFormat.currency(0.004, locale: us), "< $0.01")
        XCTAssertEqual(UsageFormat.currency(0, locale: us), "$0.00")
        let es = UsageFormat.currency(1234.5, locale: Locale(identifier: "es_ES"))
        XCTAssertTrue(es.contains("1234,50"), es)
        XCTAssertTrue(es.contains("US$") || es.contains("$"), "the code is pinned to USD, not the locale's: \(es)")
    }

    func testPercentFromAFractionAndItsDash() {
        XCTAssertEqual(UsageFormat.percent(fraction: 0.18), "18%")
        XCTAssertEqual(UsageFormat.percent(fraction: 0.125), "13%")
        XCTAssertEqual(UsageFormat.percent(fraction: nil), "—")
    }

    // MARK: Lenient decoding

    func testAnOlderHistoryAndDetailPayloadHasNoUsage() throws {
        let entry = try decode(SleepHistoryEntry.self,
                               #"{"commitHash":"abc","date":"2026-09-01","message":"m","filesChanged":[]}"#)
        XCTAssertNil(entry.usageSummary)
        let detail = try decode(SleepCycleDetail.self,
                                #"{"commitHash":"abc","date":"2026-09-01","message":"m","filesChanged":[]}"#)
        XCTAssertNil(detail.usage)
        XCTAssertNil(detail.usageSummary)
    }

    func testAMalformedUsageBlockNeverBreaksTheCycleDetail() throws {
        let detail = try decode(SleepCycleDetail.self, """
        {"commitHash":"abc","date":"2026-09-01","message":"m","filesChanged":[],
         "usage":{"recorded":"yes","models":"nope","plan":{"windows":[{"window":"five_hour"}]}},
         "usageSummary":{"plan":{"window":5}}}
        """)
        XCTAssertEqual(detail.commitHash, "abc")
        XCTAssertNil(detail.usageSummary)
        XCTAssertNil(detail.usage, "a malformed block reads as not recorded, never as a cycle with no calls")
    }

    func testTheFullUsageBlockDecodes() throws {
        let d = try decode(SleepCycleDetail.self, """
        {"commitHash":"abc","date":"2026-09-01","message":"m","filesChanged":[],
         "usage":{"recorded":true,"engine":"claude-cli","connection":"claude-plan",
           "models":[{"model":"example-model","engine":"claude-cli","calls":14,"failedCalls":1,
                      "inputTokens":182340,"outputTokens":9120,"costUsd":null,"equivCostUsd":0.42,"basis":"list"}],
           "totalCostUsd":null,"totalEquivUsd":0.42,"basis":"list",
           "plan":{"connection":"claude-plan","windows":[{"window":"five_hour","before":0.12,"after":0.18,
                    "resetsAt":1790000000,"beforeIsFirstSeen":true}]}},
         "usageSummary":{"basis":"list","equivCostUsd":0.42,"engine":"claude-cli","connection":"claude-plan",
                         "plan":{"window":"five_hour","before":0.12,"after":0.18}}}
        """)
        XCTAssertEqual(d.usage?.models.first?.calls, 14)
        XCTAssertEqual(d.usage?.models.first?.equivCostUsd, 0.42)
        XCTAssertNil(d.usage?.models.first?.costUsd)
        XCTAssertEqual(d.usage?.plan?.windows.first?.beforeIsFirstSeen, true)
        XCTAssertEqual(d.usageSummary?.plan?.after, 0.18)
    }

    func testAnOlderEngineBodyHasNoUsageAndAMalformedOneKeepsTheCandidate() throws {
        let old = try decode(SleepEngineCandidate.self,
                             #"{"id":"agent","label":"Claude plan","available":true,"connected":true,"models":[],"detail":null}"#)
        XCTAssertNil(old.usage)
        XCTAssertEqual(old.modelPrices, [:])
        let bad = try decode(SleepEngineCandidate.self, """
        {"id":"agent","label":"Claude plan","available":true,"connected":true,"models":["m"],"detail":null,
         "usage":{"kind":7},"modelPrices":{"m":"free"}}
        """)
        XCTAssertEqual(bad.id, "agent")
        XCTAssertNil(bad.usage)
        XCTAssertEqual(bad.modelPrices, [:])
    }

    // MARK: Past nights and Last cycle — one line per basis

    private func line(_ summary: CycleUsageSummary?, kind: String = "sleep") -> String? {
        CycleUsageText.summaryLine(kind: kind, summary: summary, locale: us)
    }

    func testTheRowLineIsWordedPerBasis() {
        XCTAssertEqual(line(CycleUsageSummary(basis: "charged", costUsd: 0.42, engine: "litellm",
                                              connection: "byok-openrouter")), "$0.42 charged · OpenRouter")
        XCTAssertEqual(line(CycleUsageSummary(basis: "charged", costUsd: 0.42, engine: "litellm")), "$0.42 charged · API key")
        XCTAssertEqual(line(CycleUsageSummary(basis: "list", equivCostUsd: 0.42, engine: "claude-cli")),
                       "About $0.42 at list price · Claude plan")
        XCTAssertEqual(line(CycleUsageSummary(basis: "list", equivCostUsd: 0.42, engine: "claude-cli",
                                              connection: "claude-plan",
                                              plan: CycleUsageSummaryPlan(window: "five_hour", before: 0.12, after: 0.18))),
                       "Claude plan · 5-hour window 12% → 18% · covers all your use of the plan · about $0.42 at list price")
        XCTAssertEqual(line(CycleUsageSummary(basis: "plan", engine: "codex-cli", connection: "chatgpt-plan",
                                              plan: CycleUsageSummaryPlan(window: "primary", before: 0.31, after: 0.35))),
                       "ChatGPT plan · main window 31% → 35% · covers all your use of the plan")
        XCTAssertEqual(CycleUsageText.windowShift(window: "five_hour", before: 0.4, after: 0.03),
                       "5-hour window 40% → 3% · window reset meanwhile")
        XCTAssertEqual(line(CycleUsageSummary(basis: "free", engine: "ollama")), "Ran on this Mac")
        XCTAssertEqual(line(CycleUsageSummary(basis: nil)), "No model calls")
    }

    func testNotRecordedIsSaidOnlyForACycleAndNeverForDecayOrInbox() {
        XCTAssertEqual(line(nil), "Usage not recorded")
        XCTAssertNil(line(nil, kind: "decay"))
        XCTAssertNil(line(nil, kind: "inbox"))
        XCTAssertNil(line(CycleUsageSummary(basis: "charged", costUsd: 1), kind: "decay"))
    }

    func testAPlanLineCarriesTheHonestLimitAsHelp() {
        let plan = CycleUsageSummary(basis: "plan", plan: CycleUsageSummaryPlan(window: "five_hour", before: 0.1, after: 0.2))
        XCTAssertEqual(CycleUsageText.summaryHelp(plan), Copy.SleepUsage.planNote)
        XCTAssertNil(CycleUsageText.summaryHelp(CycleUsageSummary(basis: "charged", costUsd: 1)))
    }

    // MARK: An opened cycle

    func testAModelLineStatesCallsTokensAndCostWithItsBasis() {
        let list = CycleUsageModel(model: "example-model", engine: "claude-cli", calls: 14, failedCalls: 1,
                                   inputTokens: 182_340, outputTokens: 9_120, equivCostUsd: 0.42, basis: "list")
        XCTAssertEqual(CycleUsageText.modelLine(list, locale: us),
                       "example-model · 14 calls · 1 failed · 182,340 tokens in · 9,120 tokens out · about $0.42 at list price")
        let charged = CycleUsageModel(model: "example-model", engine: "litellm", calls: 1, inputTokens: 10,
                                      outputTokens: 2, costUsd: 0.003, basis: "charged")
        XCTAssertEqual(CycleUsageText.modelLine(charged, locale: us),
                       "example-model · 1 call · 10 tokens in · 2 tokens out · < $0.01 charged")
        let plan = CycleUsageModel(model: "example-codex-model", engine: "codex-cli", calls: 9, basis: "plan")
        XCTAssertEqual(CycleUsageText.modelLine(plan, locale: us), "example-codex-model · 9 calls · tokens not reported",
                       "a plan call with no tokens never reads as zero tokens or zero dollars")
    }

    func testTotalsAndPlanRowsAndTheEmptyCases() {
        let usage = CycleUsage(engine: "claude-cli", connection: "claude-plan",
                               models: [CycleUsageModel(model: "m", engine: "claude-cli", calls: 2, inputTokens: 5,
                                                        outputTokens: 5, equivCostUsd: 0.42, basis: "list")],
                               totalEquivUsd: 0.42, basis: "list",
                               plan: CycleUsagePlan(connection: "claude-plan", windows: [
                                   CycleUsagePlanWindow(window: "five_hour", before: 0.12, after: 0.18, beforeIsFirstSeen: true)]))
        let lines = CycleUsageText.detailLines(usage, locale: us)
        XCTAssertEqual(lines.total, "Total · about $0.42 at list price")
        XCTAssertEqual(lines.plan.first?.text, "Claude plan · 5-hour window 12% → 18%")
        XCTAssertTrue(lines.plan.first?.help.contains(Copy.SleepUsage.firstSeenNote) ?? false)
        XCTAssertNil(lines.empty)
        XCTAssertEqual(CycleUsageText.detailLines(CycleUsage(totalCostUsd: 0.5, basis: "charged").with(models: [
            CycleUsageModel(model: "m", calls: 1, inputTokens: 1, outputTokens: 1, costUsd: 0.5, basis: "charged")]),
            locale: us).total, "Total · $0.50 charged")
        XCTAssertEqual(CycleUsageText.detailLines(nil).empty, "Usage not recorded")
        XCTAssertEqual(CycleUsageText.detailLines(CycleUsage()).empty, "No model calls")
        XCTAssertNil(CycleUsageText.detailLines(nil, kind: "decay").empty)
    }

    func testLastCycleGainsAUsageRowOnlyWhenOneWasRecorded() {
        XCTAssertFalse(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: nil,
                                                usageLine: "$0.42 charged · OpenRouter"))
        let rows = LastCycleRow.rows(pageError: nil, cancelled: false, capped: false, indexWarning: nil, status: nil,
                                     usageLine: "$0.42 charged · OpenRouter")
        XCTAssertEqual(rows.map(\.kind), [.usage])
        XCTAssertEqual(rows.first?.text, "$0.42 charged · OpenRouter")
        XCTAssertFalse(rows.first?.needsYou ?? true)
    }

    // MARK: The engine menu

    private func candidate(_ id: String, connected: Bool = true, usage: SleepEngineUsage?) -> SleepEngineCandidate {
        SleepEngineCandidate(id: id, label: id, available: true, connected: connected, models: [], detail: nil, usage: usage)
    }

    func testAClaudePlanRowSaysItsWindowAndWhenItResets() {
        // Reset 1_790_698_800 = 2026-09-29 16:20 UTC, four hours after `now`.
        let u = SleepEngineUsage(kind: "plan-window", window: "five_hour", usedFraction: 0.18, resetsAt: 1_790_698_800,
                                 asOf: "2026-09-29T11:50:00Z", source: "last-cycle")
        let c = CycleUsageText.caption(for: candidate("agent", usage: u), now: now, locale: us, timeZone: utc)
        XCTAssertEqual(plain(c?.caption), "18% of 5-hour window · resets 4:20 PM")
    }

    func testAStaleReadingIsAsOfItsDayAndAResetWindowSaysSo() {
        let stale = SleepEngineUsage(kind: "plan-window", window: "five_hour", usedFraction: 0.18,
                                     resetsAt: 1_790_770_000, asOf: "2026-09-28T10:20:00Z", source: "last-cycle")
        let c = CycleUsageText.caption(for: candidate("agent", usage: stale), now: now, locale: us, timeZone: utc)
        XCTAssertEqual(c?.caption, "18% of 5-hour window · as of yesterday")
        XCTAssertTrue(c?.help.contains("resets") ?? false, "the absolute time stays reachable in help")
        let reset = SleepEngineUsage(kind: "plan-window", window: "five_hour", usedFraction: 0.9,
                                     resetsAt: 1_790_600_000, asOf: "2026-09-28T10:20:00Z", source: "last-cycle")
        XCTAssertEqual(CycleUsageText.caption(for: candidate("agent", usage: reset), now: now, locale: us, timeZone: utc)?.caption,
                       Copy.SleepUsage.windowReset)
    }

    func testAChatGPTPlanRowSaysUsedAndAWeekdayBeyondADay() {
        // 2026-10-02 (Fri) 15:40 UTC.
        let u = SleepEngineUsage(kind: "plan-window", window: "fullest", usedFraction: 0.31, resetsAt: 1_790_955_600,
                                 asOf: "2026-09-29T11:59:30Z", source: "codex-snapshot")
        let c = CycleUsageText.caption(for: candidate("codex", usage: u), now: now, locale: us, timeZone: utc)
        XCTAssertEqual(plain(c?.caption), "31% used · resets Fri 3:40 PM")
    }

    func testKeyCardsShowTheirModelsPricePerMillionTokens() {
        let u = SleepEngineUsage(kind: "list-price", model: "example-model", inputPerMillionUsd: 0.4,
                                 outputPerMillionUsd: 1.6, lastCycleCostUsd: 0.42)
        XCTAssertEqual(CycleUsageText.caption(for: candidate("openrouter", usage: u), now: now, locale: us)?.caption,
                       "$0.40 in · $1.60 out per million tokens")
        XCTAssertNil(CycleUsageText.caption(for: candidate("local", usage: nil), now: now, locale: us),
                     "Ollama and Auto keep their own caption")
    }

    func testTheMenuModelUsesUsageCaptionsPricesAndTheLastCycle() {
        let plan = SleepEngineUsage(kind: "plan-window", window: "five_hour", usedFraction: 0.18,
                                    resetsAt: 1_790_698_800, asOf: "2026-09-29T11:50:00Z", source: "last-cycle")
        let key = SleepEngineUsage(kind: "list-price", model: "example-model", inputPerMillionUsd: 0.4,
                                   outputPerMillionUsd: 1.6, lastCycleCostUsd: 0.42)
        var agent = candidate("agent", usage: plan)
        agent.modelPrices = ["sonnet": SleepEngineModelPrice(inputPerMillionUsd: 3, outputPerMillionUsd: 15)]
        let r = SleepEngineResponse(
            mode: "agent", model: "sonnet", disambiguationModel: "", source: "prefs",
            candidates: [agent, candidate("codex", connected: false, usage: plan), candidate("byok", usage: key)],
            preview: SleepEnginePreviews(manual: SleepEnginePreview(engine: "claude-cli", model: "sonnet", why: ""),
                                         scheduled: SleepEnginePreview(engine: "claude-cli", model: "sonnet", why: "")))
        let m = EngineQuickMenuModel.from(r, now: now, locale: us, timeZone: utc)
        XCTAssertEqual(plain(m.rows.first { $0.id == "agent" }?.caption), "18% of 5-hour window · resets 4:20 PM")
        XCTAssertEqual(m.rows.first { $0.id == "byok" }?.caption, "$0.40 in · $1.60 out per million tokens")
        XCTAssertEqual(m.rows.first { $0.id == "codex" }?.caption, "Not signed in", "a signed-out plan keeps saying so")
        XCTAssertEqual(m.lastCycleLine, "Last cycle: $0.42 charged")
        XCTAssertEqual(m.modelPrices, ["sonnet": "$3.00 / $15.00"])
        XCTAssertEqual(m.pickerLabel("sonnet"), "sonnet · $3.00 / $15.00")
        XCTAssertEqual(m.pickerLabel("haiku"), "haiku")
    }

    func testAMenuWithNoUsageIsTheOldMenu() {
        let r = SleepEngineResponse(mode: "agent", model: "sonnet", disambiguationModel: "", source: "prefs",
                                    candidates: [candidate("agent", usage: nil)], preview: nil)
        let m = EngineQuickMenuModel.from(r)
        XCTAssertEqual(m.rows.first?.caption, "Signed in")
        XCTAssertNil(m.lastCycleLine)
        XCTAssertNil(m.pricesNote)
    }
}

private extension CycleUsage {
    func with(models: [CycleUsageModel]) -> CycleUsage {
        var copy = self
        copy.models = models
        return copy
    }
}
