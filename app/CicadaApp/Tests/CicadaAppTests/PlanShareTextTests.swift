import XCTest
@testable import CicadaApp

/// Owner 2026-10-16 — "For Claude plans could you see how much usage was used from the plan instead of money?"
/// A plan run leads with its share of each window and the share's basis (measured, under a point, or estimated —
/// never an estimate passed off as a reading, never "0%"); its dollars become the secondary "would have cost"
/// figure. Metered runs keep dollars. Every string from synthetic wire values.
final class PlanShareTextTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func share(_ window: String, _ basis: String, _ value: Double? = nil, under: Double? = nil,
                       samples: Int? = nil) -> CycleUsagePlanShare {
        CycleUsagePlanShare(window: window, basis: basis, share: value, under: under, samples: samples)
    }

    // MARK: Figures

    func testEachBasisIsWordedAndNothingReadsZero() {
        XCTAssertEqual(CycleUsageText.shareFigure(share("seven_day", "measured", 0.03), locale: us),
                       "about 3% of your weekly limit")
        XCTAssertEqual(CycleUsageText.shareFigure(share("five_hour", "under", under: 0.01), locale: us),
                       "under 1% of the 5-hour window")
        XCTAssertEqual(CycleUsageText.shareFigure(share("seven_day", "estimated", 0.004, under: 0.01, samples: 3),
                                                  locale: us), "about 0.4% of your weekly limit")
        XCTAssertEqual(CycleUsageText.shareFigure(share("seven_day", "estimated", 0.0002), locale: us),
                       "under 0.1% of your weekly limit", "a tiny estimate is never rounded to 0%")
        XCTAssertNil(CycleUsageText.shareFigure(share("seven_day", "under"), locale: us), "no bound, no figure")
        XCTAssertNil(CycleUsageText.shareFigure(share("seven_day", "measured", 0), locale: us))
        XCTAssertNil(CycleUsageText.shareFigure(share("seven_day", "guessed", 0.2), locale: us))
        for value in [0.0002, 0.004, 0.009, 0.03] {
            let text = UsageFormat.share(fraction: max(value, 0.001), locale: us)
            XCTAssertNotEqual(text, "0%", "\(value)")
        }
        XCTAssertEqual(UsageFormat.share(fraction: 0.004, locale: Locale(identifier: "es_ES"))
            .replacingOccurrences(of: "\u{00A0}", with: " "), "0,4 %")
    }

    func testTheLineLeadsWithTheWeeklyLimitAndSaysItsBasisOnce() {
        let measured = [share("seven_day", "measured", 0.01), share("five_hour", "under", under: 0.01)]
        XCTAssertEqual(CycleUsageText.shareLine(measured, locale: us),
                       "about 1% of your weekly limit (measured) · under 1% of the 5-hour window (reading unchanged)",
                       "\"measured\" only for a reading that moved")
        let unmoved = [share("seven_day", "under", under: 0.01), share("five_hour", "under", under: 0.01)]
        XCTAssertEqual(CycleUsageText.shareLine(unmoved, locale: us),
                       "under 1% of your weekly limit · under 1% of the 5-hour window · reading unchanged")
        let estimated = [share("seven_day", "estimated", 0.004, under: 0.01, samples: 2)]
        XCTAssertEqual(CycleUsageText.shareLine(estimated, locale: us), "about 0.4% of your weekly limit · estimated")
        let mixed = [share("seven_day", "under", under: 0.01), share("five_hour", "estimated", 0.02, samples: 4)]
        XCTAssertEqual(CycleUsageText.shareLine(mixed, locale: us),
                       "under 1% of your weekly limit (reading unchanged) · about 2% of the 5-hour window (estimated)")
        XCTAssertEqual(CycleUsageText.shareLine(measured, limit: 1, locale: us), "about 1% of your weekly limit · measured")
        XCTAssertNil(CycleUsageText.shareLine([], locale: us), "unknown stays unknown")
    }

    func testTheHelpStatesEveryBasisInFullAndTheDollarsSecond() throws {
        let help = try XCTUnwrap(CycleUsageText.shareHelp(
            [share("seven_day", "under", under: 0.01), share("five_hour", "estimated", 0.004, under: 0.01, samples: 3)],
            equivUsd: 0.49, locale: us))
        XCTAssertTrue(help.hasPrefix("Under 1% of your weekly limit · about 0.4% of the 5-hour window."), help)
        XCTAssertFalse(help.contains(Copy.SleepUsage.measuredNote), "no reading moved, so nothing is called measured")
        XCTAssertTrue(help.contains(Copy.SleepUsage.planNote), help)
        XCTAssertTrue(help.contains(Copy.SleepUsage.underNote), help)
        XCTAssertTrue(help.contains(Copy.SleepUsage.estimatedNote(samples: 3)), help)
        XCTAssertTrue(help.contains("3 earlier runs"), help)
        XCTAssertTrue(help.contains(Copy.SleepUsage.estimateCappedNote), help)
        XCTAssertTrue(help.hasSuffix("Would have cost about $0.49 on an API key."), help)
        let measuredOnly = try XCTUnwrap(CycleUsageText.shareHelp([share("seven_day", "measured", 0.02)], equivUsd: nil,
                                                                  locale: us))
        XCTAssertFalse(measuredOnly.contains("Estimated"), "a measurement is never described as an estimate")
        XCTAssertTrue(measuredOnly.contains(Copy.SleepUsage.measuredNote), measuredOnly)
        XCTAssertNil(CycleUsageText.shareHelp([], equivUsd: 0.49, locale: us))
    }

    // MARK: Placement — rows, Last cycle, an opened run

    func testARowLeadsWithTheShareAndKeepsDollarsInItsHelp() throws {
        let s = CycleUsageSummary(basis: "list", equivCostUsd: 0.49, engine: "claude-cli", connection: "claude-plan",
                                  plan: CycleUsageSummaryPlan(window: "seven_day", before: 0.27, after: 0.27),
                                  planShare: [share("seven_day", "under", under: 0.01), share("five_hour", "measured", 0.02)])
        let line = try XCTUnwrap(CycleUsageText.summaryLine(kind: "sleep", summary: s, locale: us))
        XCTAssertEqual(line, "Claude plan · under 1% of your weekly limit · reading unchanged")
        XCTAssertFalse(line.contains("$") || line.contains("0%"), line)
        XCTAssertEqual(CycleUsageText.lastCycleLine(s, locale: us), line, "Last cycle says the same short figure")
        let help = try XCTUnwrap(CycleUsageText.summaryHelp(s, locale: us))
        XCTAssertTrue(help.contains("about 2% of the 5-hour window"), "the help holds every window: \(help)")
        XCTAssertTrue(help.contains("Would have cost about $0.49 on an API key."), help)
    }

    func testAMeteredRowKeepsItsDollarsAndARunContinuedOnAKeyKeepsItsCharge() {
        let metered = CycleUsageSummary(basis: "charged", costUsd: 0.42, engine: "litellm", connection: "byok-openrouter")
        XCTAssertEqual(CycleUsageText.summaryLine(kind: "sleep", summary: metered, locale: us), "$0.42 charged · OpenRouter")
        XCTAssertNil(CycleUsageText.summaryHelp(metered, locale: us))
        let mixed = CycleUsageSummary(basis: "mixed", costUsd: 0.9, equivCostUsd: 3.1, engine: "claude-cli",
                                      connection: "claude-plan", planShare: [share("seven_day", "measured", 0.02)])
        XCTAssertEqual(CycleUsageText.summaryLine(kind: "sleep", summary: mixed, locale: us),
                       "Claude plan · about 2% of your weekly limit · measured · $0.90 charged")
    }

    func testAnOpenedPlanRunLeadsWithItsShareAndMovesItsDollarsToASecondaryLine() throws {
        let u = CycleUsage(engine: "claude-cli", connection: "claude-plan",
                           models: [CycleUsageModel(model: "example-model", engine: "claude-cli", calls: 40,
                                                    inputTokens: 900_000, outputTokens: 30_000, equivCostUsd: 0.49,
                                                    basis: "list")],
                           totalEquivUsd: 0.49, basis: "list",
                           plan: CycleUsagePlan(connection: "claude-plan", windows: [
                               CycleUsagePlanWindow(window: "seven_day", before: 0.27, after: 0.27, beforeIsFirstSeen: true)]),
                           planShare: [share("seven_day", "under", under: 0.01)])
        let lines = CycleUsageText.detailLines(u, locale: us)
        XCTAssertEqual(lines.share?.text, "under 1% of your weekly limit · reading unchanged")
        XCTAssertTrue(lines.share?.help.contains(Copy.SleepUsage.underNote) ?? false)
        XCTAssertEqual(lines.equiv, "Would have cost about $0.49 on an API key")
        XCTAssertNil(lines.total)
        XCTAssertFalse(lines.models.joined().contains("$"), "a plan run's model lines carry no price: \(lines.models)")
        XCTAssertEqual(lines.plan.first?.text, "Claude plan · weekly window 27% → 27%", "the readings stay as detail")
        let metered = CycleUsage(engine: "litellm", connection: "byok-openai",
                                 models: [CycleUsageModel(model: "m", engine: "litellm", calls: 1, inputTokens: 1,
                                                          outputTokens: 1, costUsd: 0.5, basis: "charged")],
                                 totalCostUsd: 0.5, basis: "charged")
        let m = CycleUsageText.detailLines(metered, locale: us)
        XCTAssertNil(m.share)
        XCTAssertNil(m.equiv)
        XCTAssertEqual(m.total, "Total · $0.50 charged")
    }

    /// The share line sits above the models in both opened views, and the "would have cost" line under the total;
    /// the engine menu's line carries its help. Source order is the visual order in a VStack.
    func testTheViewsPlaceTheShareFirstAndTheDollarsSecond() throws {
        for name in ["RunDetailView.swift", "ConsolidationHistoryCard.swift"] {
            let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.lastPathComponent == name })
            let text = try String(contentsOf: file, encoding: .utf8)
            let share = try XCTUnwrap(text.range(of: "if let share = lines.share"), name)
            let models = try XCTUnwrap(text.range(of: "SectionLabel(Copy.SleepUsage.modelsTitle)"), name)
            let total = try XCTUnwrap(text.range(of: "if let total = lines.total"), name)
            let equiv = try XCTUnwrap(text.range(of: "if let equiv = lines.equiv"), name)
            XCTAssertLessThan(share.lowerBound, models.lowerBound, name)
            XCTAssertLessThan(total.lowerBound, equiv.lowerBound, name)
        }
        let menu = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "EngineQuickMenu.swift" })
        XCTAssertTrue(try String(contentsOf: menu, encoding: .utf8).contains(".help(model.lastCycleHelp"))
    }

    // MARK: The engine menu

    private func candidate(_ id: String, usage: SleepEngineUsage?) -> SleepEngineCandidate {
        SleepEngineCandidate(id: id, label: id, available: true, connected: true, models: [], detail: nil, usage: usage)
    }

    func testThePlanCardsLastRunIsItsShareWithTheDollarsInHelp() throws {
        let plan = SleepEngineUsage(kind: "plan-window", source: "last-cycle",
                                    lastRunShare: [share("seven_day", "under", under: 0.01)], lastRunEquivUsd: 0.49)
        let key = SleepEngineUsage(kind: "list-price", model: "m", inputPerMillionUsd: 0.4, outputPerMillionUsd: 1.6,
                                   lastCycleCostUsd: 0.42)
        let both = [candidate("byok", usage: key), candidate("agent", usage: plan)]
        let last = try XCTUnwrap(CycleUsageText.lastCycle(both, preferring: "agent", locale: us))
        XCTAssertEqual(last.line, "Last run: under 1% of your weekly limit · reading unchanged")
        XCTAssertTrue(last.help?.hasSuffix("Would have cost about $0.49 on an API key.") ?? false, last.help ?? "")
        XCTAssertEqual(CycleUsageText.lastCycleLine(both, preferring: "byok", locale: us), "Last cycle: $0.42 charged",
                       "a metered card keeps its dollars")
        let r = SleepEngineResponse(mode: "agent", model: "sonnet", disambiguationModel: "", source: "prefs",
                                    candidates: both,
                                    preview: SleepEnginePreviews(
                                        manual: SleepEnginePreview(engine: "claude-cli", model: "sonnet", why: ""),
                                        scheduled: SleepEnginePreview(engine: "claude-cli", model: "sonnet", why: "")))
        let m = EngineQuickMenuModel.from(r, locale: us)
        XCTAssertEqual(m.lastCycleLine, "Last run: under 1% of your weekly limit · reading unchanged")
        XCTAssertNotNil(m.lastCycleHelp)
        XCTAssertEqual(m.rows.first { $0.id == "agent" }?.caption, "Signed in",
                       "a plan card with no window reading keeps its own caption")
    }

    // MARK: Decoding

    func testTheShareDecodesAndAnOlderOrMalformedOneIsEmptyNeverFatal() throws {
        let json = """
        {"basis":"list","equivCostUsd":0.49,"engine":"claude-cli","connection":"claude-plan",
         "planShare":[{"window":"seven_day","basis":"under","share":null,"under":0.01,"samples":null},
                      {"window":"five_hour","basis":"estimated","share":0.004,"under":0.01,"samples":3}]}
        """
        let s = try JSONDecoder().decode(CycleUsageSummary.self, from: Data(json.utf8))
        XCTAssertEqual(s.planShare.map(\.basis), ["under", "estimated"])
        XCTAssertEqual(s.planShare.last?.samples, 3)
        XCTAssertNil(s.planShare.first?.share)
        let old = try JSONDecoder().decode(CycleUsageSummary.self, from: Data(#"{"basis":"list"}"#.utf8))
        XCTAssertEqual(old.planShare, [])
        let bad = try JSONDecoder().decode(CycleUsage.self,
                                           from: Data(#"{"recorded":true,"models":[],"planShare":"nope"}"#.utf8))
        XCTAssertEqual(bad.planShare, [])
        XCTAssertTrue(bad.recorded)
        let engine = try JSONDecoder().decode(SleepEngineUsage.self, from: Data(#"{"kind":"plan-window"}"#.utf8))
        XCTAssertNil(engine.lastRunShare)
    }
}
