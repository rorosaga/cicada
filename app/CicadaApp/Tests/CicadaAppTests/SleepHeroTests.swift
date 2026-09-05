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

    // MARK: heroTiles — R-A6: present tense or measured, never a forecast

    func test_heroTiles_areAlwaysThree_andMeasured() {
        let tiles = heroTiles(entityCount: 1_904, sourceCount: 6, lastDurationMs: 252_000)
        XCTAssertEqual(tiles.count, 3)
        XCTAssertEqual(tiles.map(\.value), ["1904", "6", "4 m 12 s"])
        XCTAssertEqual(tiles.map(\.label), ["entities in memory", "sources feeding it", "Last cycle"])
        XCTAssertTrue(tiles.allSatisfy { $0.reason == nil }, "a real value carries no dash reason")
    }

    /// R-A14/P18 — `—` is a value with a reason, never a blank and never a
    /// zero standing in for an unknown.
    func test_heroTiles_useADashWithAReasonForEveryUnknown() {
        let tiles = heroTiles(entityCount: nil, sourceCount: nil, lastDurationMs: nil)
        XCTAssertEqual(tiles.count, 3)
        for tile in tiles {
            XCTAssertEqual(tile.value, "—", "\(tile.label) invented a number it does not have")
            XCTAssertFalse((tile.reason ?? "").isEmpty, "\(tile.label): every dash names why")
        }
    }

    func test_heroTiles_pluraliseTheirNouns() {
        let one = heroTiles(entityCount: 1, sourceCount: 1, lastDurationMs: 900)
        XCTAssertEqual(one.map(\.label), ["entity in memory", "source feeding it", "Last cycle"])
        XCTAssertEqual(one.map(\.value), ["1", "1", "0 s"])
    }

    /// The refused words (R-A6, G107): no forecast, no "clusters", no
    /// estimate — asserted over the label, the value AND the dash reason,
    /// since all three are read by the human.
    func test_heroTiles_neverForecastAnything() {
        let cases = [
            heroTiles(entityCount: 1_904, sourceCount: 6, lastDurationMs: 252_000),
            heroTiles(entityCount: nil, sourceCount: nil, lastDurationMs: nil),
        ]
        for tiles in cases {
            for tile in tiles {
                let text = "\(tile.label) \(tile.value) \(tile.reason ?? "")".lowercased()
                for banned in ["cluster", "insight", "est", "~"] {
                    XCTAssertFalse(text.contains(banned), "\"\(text)\" contains \"\(banned)\"")
                }
            }
        }
    }
}
