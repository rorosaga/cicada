import XCTest
@testable import CicadaApp

/// The Sleep page's hero readout (G125 v3 Task 4 — spec R-A4…R-A7). Every
/// function under test is pure, so none of this stands a view up: the count,
/// the qualifier chip, the caption tail, the meter and the three tiles are
/// asserted directly, exactly like the rest of `Views/Sleep/`.
final class SleepHeroTests: XCTestCase {

    /// Mirrors `SleepMoodTests.debtView` — `SleepDebtView` is a plain struct,
    /// so no JSON round-trip is needed here.
    private func debtView(
        restedPct: Int? = 100, volumePct: Int = 0, agePct: Int = 0,
        unprocessedCount: Int = 0, hasRunBefore: Bool = true, hoursSinceLastCycle: Double? = 0
    ) -> SleepDebtView {
        SleepDebtView(restedPct: restedPct, volumePct: volumePct, agePct: agePct,
                      unprocessedCount: unprocessedCount, hasRunBefore: hasRunBefore,
                      hoursSinceLastCycle: hoursSinceLastCycle)
    }

    // MARK: The composition is byte-for-byte (P8)

    /// `sleepDebtBracketText` is now `heroCount` + `bracketTail` re-composed,
    /// never rewritten. All twelve strings `SleepMoodTests` asserts are
    /// re-asserted HERE too, so the composition is pinned in the file that
    /// owns the two halves as well as in the file that owns the whole — a
    /// future edit to either half fails in both places, never silently in
    /// neither.
    func test_bracketText_survivesTheDecompositionByteForByte() {
        XCTAssertEqual(sleepDebtBracketText(.awake, debt: nil), "[ awake ]")
        XCTAssertEqual(sleepDebtBracketText(.sleeping(stage: 2), debt: nil), "[ sleeping · stage 2 of 5 ]")
        XCTAssertEqual(sleepDebtBracketText(.digesting, debt: nil), "[ digesting ]")
        XCTAssertEqual(sleepDebtBracketText(.happy, debt: nil), "[ caught up ]")
        XCTAssertEqual(sleepDebtBracketText(.curious(count: 47), debt: nil), "[ 47 episodes behind ]")
        XCTAssertEqual(sleepDebtBracketText(.curious(count: 1), debt: nil), "[ 1 episode behind ]")
        XCTAssertEqual(sleepDebtBracketText(.hungry, debt: debtView(unprocessedCount: 30)),
                       "[ 30 episodes behind — overdue ]")
        XCTAssertEqual(sleepDebtBracketText(.hungry, debt: debtView(unprocessedCount: 1)),
                       "[ 1 episode behind — overdue ]")
        XCTAssertEqual(sleepDebtBracketText(.hungry, debt: debtView(unprocessedCount: 0)),
                       "[ overdue — hasn't consolidated in a while ]")
        XCTAssertEqual(sleepDebtBracketText(.hungry, debt: nil),
                       "[ overdue — hasn't consolidated in a while ]")
        XCTAssertEqual(sleepDebtBracketText(.error, debt: nil), "[ last cycle failed ]")
        XCTAssertEqual(sleepDebtBracketText(.reading, debt: debtView(unprocessedCount: 12)), "[ 12 to read ]")
        XCTAssertEqual(sleepDebtBracketText(.reading, debt: nil), "[ 0 to read ]")
    }

    // MARK: heroCount — the numeral, and only when there is one

    func test_heroCount_isTheNumeralTheBracketWouldHaveShown() {
        XCTAssertEqual(heroCount(.reading, debt: debtView(unprocessedCount: 12)), 12)
        // `.curious`'s numeral comes from the CASE, not from `debt` — the
        // menu-bar-shaped state carries its own count and is asserted with a
        // nil debt in `SleepMoodTests`.
        XCTAssertEqual(heroCount(.curious(count: 47), debt: nil), 47)
        XCTAssertEqual(heroCount(.hungry, debt: debtView(unprocessedCount: 30)), 30)
        XCTAssertNil(heroCount(.happy, debt: debtView(unprocessedCount: 0)))
        XCTAssertNil(heroCount(.sleeping(stage: 2), debt: debtView(unprocessedCount: 9)))
        XCTAssertNil(heroCount(.hungry, debt: debtView(unprocessedCount: 0)))
        XCTAssertNil(heroCount(.awake, debt: nil))
        XCTAssertNil(heroCount(.digesting, debt: nil))
        XCTAssertNil(heroCount(.error, debt: nil))
    }

    /// `.reading` never returns nil — `"[ 0 to read ]"` with a nil debt is an
    /// asserted string. The hero VIEW is what decides not to draw a `0`;
    /// `heroCount` does not lie about it.
    func test_heroCount_readingIsZeroNotNil_whenTheDebtHasNotLoaded() {
        XCTAssertEqual(heroCount(.reading, debt: nil), 0)
    }

    // MARK: heroQualifier — the short chip beside the numeral

    func test_heroQualifier_namesTheStateInOneOrTwoWords() {
        XCTAssertEqual(heroQualifier(.happy, debt: debtView()), "caught up")
        XCTAssertEqual(heroQualifier(.hungry, debt: debtView(unprocessedCount: 30)), "overdue")
        XCTAssertEqual(heroQualifier(.hungry, debt: debtView(unprocessedCount: 0)), "overdue")
        XCTAssertEqual(heroQualifier(.reading, debt: debtView(unprocessedCount: 12, hasRunBefore: true)), "behind")
        XCTAssertEqual(heroQualifier(.curious(count: 47), debt: nil), "behind")
        XCTAssertEqual(heroQualifier(.error, debt: nil), "failed")
        XCTAssertEqual(heroQualifier(.awake, debt: nil), "awake")
        XCTAssertEqual(heroQualifier(.sleeping(stage: 3), debt: nil), "sleeping")
        XCTAssertEqual(heroQualifier(.digesting, debt: nil), "digesting")
        // `intakeInFlight` holds `.reading` with an as-yet-unrefreshed queue
        // of 0 (G125 R2) — nothing is behind, the worm is simply busy.
        XCTAssertEqual(heroQualifier(.reading, debt: debtView(unprocessedCount: 0)), "reading")
    }

    /// P9 — nothing has ever been consolidated in this bank, so calling the
    /// queue a *backlog* would be wrong. Outranks `behind` and `overdue`.
    func test_heroQualifier_saysFirstRun_whenSleepHasNeverRunHere() {
        XCTAssertEqual(heroQualifier(.reading, debt: debtView(unprocessedCount: 12, hasRunBefore: false)),
                       "first run")
        XCTAssertEqual(heroQualifier(.hungry, debt: debtView(unprocessedCount: 30, hasRunBefore: false)),
                       "first run")
        // …but never for an empty queue: there is no first run to name.
        XCTAssertEqual(heroQualifier(.hungry, debt: debtView(unprocessedCount: 0, hasRunBefore: false)),
                       "overdue")
    }

    // MARK: heroMeter — R-A5, as a test

    func test_heroMeter_isHiddenWhenThereIsNoBaseline() {
        XCTAssertNil(heroMeter(mood: .happy, debt: debtView(restedPct: nil), read: 0, total: 0),
                     "no baseline — Sleep has never run in this bank — is not a 100%")
        XCTAssertNil(heroMeter(mood: .awake, debt: nil, read: 0, total: 0))
    }

    func test_heroMeter_whileIdleReadsRestedPct() {
        let meter = heroMeter(mood: .reading, debt: debtView(restedPct: 12, unprocessedCount: 40),
                              read: 0, total: 0)
        XCTAssertEqual(meter, .rested(pct: 12))
        XCTAssertEqual(meter?.label, "Rested 12%")
    }

    /// P7 — the label's two numbers and the bar's fraction come from ONE
    /// reading: the sums of `resolveOriginCounts`, already resolved once per
    /// body eval. Never `progressPct`, which is a different scalar on a
    /// different cadence.
    func test_heroMeter_whileRunningReadsTheOriginSums() {
        let meter = heroMeter(mood: .sleeping(stage: 1), debt: debtView(restedPct: 12),
                              read: 138, total: 203)
        XCTAssertEqual(meter, .reading(read: 138, total: 203))
        XCTAssertEqual(meter?.label, "Read 138 of 203")
        XCTAssertEqual(meter?.fraction ?? 0, 138.0 / 203.0, accuracy: 1e-9)
        XCTAssertEqual(meter?.filledBlocks, 16)
    }

    /// A running cycle with nothing countable yet (stages 2–5 have no
    /// per-episode unit) draws no bar at all rather than `Read 0 of 0`.
    func test_heroMeter_whileRunningWithNoCountableUnitIsHidden() {
        XCTAssertNil(heroMeter(mood: .sleeping(stage: 3), debt: debtView(restedPct: 40), read: 0, total: 0))
    }

    /// **The bar never renders without its noun** (R-A5). A matrix over every
    /// mood × a baseline/no-baseline debt × idle/running counts: whenever the
    /// meter is non-nil its label is non-empty and names what it is measuring.
    func test_heroMeter_neverRendersWithoutItsNoun() {
        let moods: [BookwormState] = [
            .awake, .sleeping(stage: 1), .sleeping(stage: 4), .digesting,
            .happy, .curious(count: 3), .reading, .hungry, .error,
        ]
        let debts: [SleepDebtView?] = [
            nil, debtView(restedPct: nil), debtView(restedPct: 0), debtView(restedPct: 100),
            debtView(restedPct: 12, unprocessedCount: 40, hasRunBefore: false),
        ]
        for mood in moods {
            for debt in debts {
                for (read, total) in [(0, 0), (0, 203), (138, 203), (203, 203)] {
                    guard let meter = heroMeter(mood: mood, debt: debt, read: read, total: total) else { continue }
                    XCTAssertFalse(meter.label.isEmpty, "\(mood) drew a bar with an empty label")
                    XCTAssertTrue(meter.label.hasPrefix("Rested ") || meter.label.hasPrefix("Read "),
                                  "\(mood) drew a bar whose label names no noun: \(meter.label)")
                    XCTAssertTrue((0...1).contains(meter.fraction), "\(mood): fraction \(meter.fraction) is out of range")
                    XCTAssertTrue((0...HeroMeter.blockCount).contains(meter.filledBlocks),
                                  "\(mood): \(meter.filledBlocks) filled blocks of \(HeroMeter.blockCount)")
                }
            }
        }
    }

    func test_heroMeter_fillsWholeBlocksOnly() {
        XCTAssertEqual(HeroMeter.blockCount, 24)
        XCTAssertEqual(HeroMeter.rested(pct: 0).filledBlocks, 0)
        XCTAssertEqual(HeroMeter.rested(pct: 100).filledBlocks, 24)
        XCTAssertEqual(HeroMeter.rested(pct: 50).filledBlocks, 12)
        // A percentage above the range can only come from a backend bug —
        // clamp rather than draw 26 blocks into a 24-block bar.
        XCTAssertEqual(HeroMeter.rested(pct: 140).filledBlocks, 24)
        XCTAssertEqual(HeroMeter.reading(read: 5, total: 0).filledBlocks, 0)
    }

    // MARK: heroMeterHelp — the breakdown that used to be a second line

    /// Round-2 live check (R-A5): the page printed `Rested n%` in the hero's
    /// labelled meter and printed it AGAIN under the stage strip as
    /// `Rested n% — volume v%, age a%`. The duplicate is gone; the volume/age
    /// split it carried survives as the meter label's hover text, so nothing
    /// the page knew was lost — it just stopped being said twice.
    func test_heroMeterHelp_carriesTheVolumeAndAgeSplit() {
        let debt = debtView(restedPct: 42, volumePct: 30, agePct: 12)
        let meter = heroMeter(mood: .curious(count: 8), debt: debt, read: 0, total: 0)
        XCTAssertEqual(meter, .rested(pct: 42))
        XCTAssertEqual(heroMeterHelp(meter!, debt: debt),
                       "Volume 30% · age 12% of the way to a full backlog")
    }

    /// Every percentage names its noun, in a tooltip exactly as on the page
    /// (R-A5/R-A15) — a hover that read "30% · 12%" would be the same defect
    /// one layer down.
    func test_heroMeterHelp_namesWhatEachPercentageIsOf() {
        let help = Copy.restedBreakdown(volumePct: 0, agePct: 100)
        XCTAssertTrue(help.contains("Volume 0%"))
        XCTAssertTrue(help.contains("age 100%"))
        XCTAssertTrue(help.contains("backlog"), "a percentage with no noun is what R-A5 refuses")
    }

    /// `Read a of b` already shows both of its numbers, so there is nothing
    /// left for a tooltip to explain — and a debt that never loaded has no
    /// breakdown to state rather than a fabricated `0% · 0%`.
    func test_heroMeterHelp_isNilWhenThereIsNothingToExplain() {
        let running = HeroMeter.reading(read: 138, total: 203)
        XCTAssertNil(heroMeterHelp(running, debt: debtView(volumePct: 30, agePct: 12)))
        XCTAssertNil(heroMeterHelp(.rested(pct: 42), debt: nil))
    }

    // MARK: readoutRows — R-A6's measured values as rows (R-HS15)

    func test_readoutRowsAreFourAndMeasured() {
        let en = Locale(identifier: "en_US")
        let rows = readoutRows(entityCount: 1_904, sourceCount: 6, lastDurationMs: 252_000, lastEngine: "claude-cli",
                               engineDetail: nil, locale: en)
        XCTAssertEqual(rows.map(\.key), ["In memory", "Feeding it", "Last cycle took", "Last engine"])
        XCTAssertEqual(rows.map(\.value), ["1,904 entities", "6 sources", "4 m 12 s", Copy.engineLabel("claude-cli")])
        XCTAssertTrue(rows.allSatisfy { $0.reason == nil }, "a real value carries no dash reason")
        XCTAssertEqual(rows.last?.engine, "claude-cli", "the engine row wears its mark (DR-52)")
        // de_DE, not es_ES: CLDR gives es_ES `minimumGroupingDigits = 2`, so Spanish leaves a
        // four-digit count ungrouped ("1904") — `SourcesV2Tests` records the same choice.
        XCTAssertEqual(readoutRows(entityCount: 1_904, sourceCount: 1, lastDurationMs: nil, lastEngine: nil,
                                   engineDetail: nil, locale: Locale(identifier: "de_DE")).first?.value,
                       "1.904 entities", "DR-21 — the reader's locale, never String(n)")
    }

    func test_readoutRowsUseADashWithAReasonForEveryUnknown() {
        for row in readoutRows(entityCount: nil, sourceCount: nil, lastDurationMs: nil, lastEngine: nil, engineDetail: nil) {
            XCTAssertEqual(row.value, "—", "\(row.key) invented a value it does not have")
            XCTAssertFalse((row.reason ?? "").isEmpty, "\(row.key): every dash names why")
        }
    }

    func test_readoutRowsPluraliseAndNeverForecast() {
        let one = readoutRows(entityCount: 1, sourceCount: 1, lastDurationMs: 900, lastEngine: "ollama",
                              engineDetail: "example-local", locale: Locale(identifier: "en_US"))
        XCTAssertEqual(one.map(\.value), ["1 entity", "1 source", "0 s", "\(Copy.engineLabel("ollama")) · example-local"])
        for row in one {
            let text = "\(row.key) \(row.value) \(row.reason ?? "")".lowercased()
            for banned in ["cluster", "insight", "estimate", "~", "$", "token"] {
                XCTAssertFalse(text.contains(banned), "\"\(text)\" contains \"\(banned)\"")
            }
        }
    }

    // MARK: The meter is a sentence (DESIGN_RULES §10, Sleep; R-HS15)

    func test_theRestedMeterIsASentence() {
        XCTAssertEqual(HeroMeter.rested(pct: 100).sentence(unprocessed: 0, mood: .happy),
                       "Fully rested — nothing is waiting.")
        XCTAssertEqual(HeroMeter.rested(pct: 0).sentence(unprocessed: 40, mood: .hungry),
                       "Rested 0% — the backlog is overdue.")
        XCTAssertEqual(HeroMeter.rested(pct: 40).sentence(unprocessed: 3, mood: .reading),
                       "Rested 40% — based on how much is waiting, and for how long.")
        XCTAssertEqual(HeroMeter.reading(read: 2, total: 3).sentence(unprocessed: 3, mood: .sleeping(stage: 1)),
                       "Read 2 of 3 so far.")
        for meter in [HeroMeter.rested(pct: 12), .rested(pct: 100), .reading(read: 1, total: 9)] {
            let s = meter.sentence(unprocessed: 5, mood: .awake)
            XCTAssertTrue(s.hasSuffix("."), s)
            XCTAssertTrue(s.hasPrefix("Rested") || s.hasPrefix("Read") || s.hasPrefix("Fully"), "\(s) — the noun first (R-A5)")
        }
    }
}
