import XCTest
@testable import CicadaApp

/// G125 Task 7 — the consolidation history card's pure presentation layer:
/// how long a cycle took, its one-line summary, and its date, each a static
/// function so the exact wording is asserted without standing up a view.
final class SleepHistoryPresentationTests: XCTestCase {

    // MARK: durationText

    func testDurationTextIsAnEmDashWhenNoLedgerRowJoined() {
        XCTAssertEqual(SleepHistoryPresentation.durationText(ms: nil), "—")
    }

    func testDurationTextUnderAMinuteIsWholeSeconds() {
        XCTAssertEqual(SleepHistoryPresentation.durationText(ms: 4_200), "4 s")
    }

    func testDurationTextUnderAnHourIsMinutesAndSeconds() {
        XCTAssertEqual(SleepHistoryPresentation.durationText(ms: 252_000), "4 m 12 s")
    }

    func testDurationTextOverAnHourIsHoursAndMinutes() {
        XCTAssertEqual(SleepHistoryPresentation.durationText(ms: 3_700_000), "1 h 2 m")
    }

    // MARK: summaryLine

    private func entry(kind: String = "sleep", created: Int = 0, updated: Int = 0,
                       episodes: Int = 0, engine: String? = nil,
                       authors: [String] = []) throws -> SleepHistoryEntry {
        let engineField = engine.map { "\"engine\":\"\($0)\"," } ?? ""
        let authorsField = authors.map { "\"\($0)\"" }.joined(separator: ",")
        let json = """
        {"commitHash":"abc123","date":"2026-09-01","message":"Sleep cycle 2026-09-01",
         "filesChanged":[],\(engineField)"kind":"\(kind)","entitiesCreated":\(created),
         "entitiesUpdated":\(updated),"episodes":\(episodes),"authors":[\(authorsField)]}
        """
        return try JSONDecoder().decode(SleepHistoryEntry.self, from: Data(json.utf8))
    }

    func testSummaryLineNamesNewAndUpdatedCounts() throws {
        let e = try entry(created: 12, updated: 8)
        XCTAssertEqual(SleepHistoryPresentation.summaryLine(e), "+12 new · 8 updated")
    }

    func testSummaryLineForADecayCommitNamesItAPass() throws {
        // A G85-split decay commit touches entities too, but it is arithmetic,
        // not extraction — the summary must say so rather than claiming "new"/
        // "updated" work an LLM never did.
        let e = try entry(kind: "decay", created: 0, updated: 5)
        XCTAssertEqual(SleepHistoryPresentation.summaryLine(e), "decay pass")
    }

    /// G125 v3 Task 7 (budget row #18) — a cycle's row leads with what it READ
    /// before what it wrote: "2 episodes → +12 new · 8 updated" answers "where
    /// did those entities come from" in the same glance.
    func testSummaryLineLeadsWithTheEpisodeCount() throws {
        XCTAssertEqual(SleepHistoryPresentation.summaryLine(try entry(created: 12, updated: 8, episodes: 2)),
                       "2 episodes → +12 new · 8 updated")
        XCTAssertEqual(SleepHistoryPresentation.summaryLine(try entry(created: 3, updated: 0, episodes: 1)),
                       "1 episode → +3 new · 0 updated")
    }

    /// P18, and the reason this is not the plan's unconditional prefix: a
    /// commit whose manifest carries no episode count (an older backend, a
    /// cached snapshot, an inbox commit) decodes `episodes` as the field's
    /// DEFAULT zero, and "0 episodes →" would be a fabricated zero standing in
    /// for an unknown. The prefix is drawn only where there is a count.
    func testSummaryLineOmitsAnAbsentEpisodeCountRatherThanDrawingAZero() throws {
        XCTAssertEqual(SleepHistoryPresentation.summaryLine(try entry(created: 12, updated: 8)),
                       "+12 new · 8 updated")
    }

    /// A decay pass reads no episodes at all — the prefix must not appear on it
    /// under any count (G85: it claims no extraction credit).
    func testSummaryLineForADecayCommitStaysAPassEvenWithEpisodes() throws {
        XCTAssertEqual(SleepHistoryPresentation.summaryLine(try entry(kind: "decay", updated: 5, episodes: 3)),
                       "decay pass")
    }

    // MARK: enginePill

    /// The row's badge slot: which engine ran the cycle, and who authored the
    /// writes. Both are already parsed server-side; neither is invented.
    func testEnginePillNamesTheEngineAndTheAuthor() throws {
        let e = try entry(engine: "claude-cli", authors: ["gpt-5.4-mini"])
        XCTAssertEqual(SleepHistoryPresentation.enginePill(e), "Claude Code (your plan) · gpt-5.4-mini")
    }

    /// A decay or state-snapshot commit legitimately carries no
    /// `Cicada-Engine:` trailer (CLAUDE.md: "omitted entirely rather than
    /// guessed"), so the pill drops its left half rather than defaulting to
    /// whichever engine happens to be configured.
    func testEnginePillDropsItsLeftHalfWhenNoEngineRan() throws {
        XCTAssertEqual(SleepHistoryPresentation.enginePill(try entry(kind: "decay", authors: ["cicada"])),
                       "cicada")
    }

    /// `user` is shown as "you" here for the same reason it is in the expanded
    /// detail — a person reads the raw literal as a model that ran.
    func testEnginePillCallsTheUserYou() throws {
        XCTAssertEqual(SleepHistoryPresentation.enginePill(try entry(authors: ["user"])), "you")
    }

    /// Nothing to say → no pill, never an empty badge.
    func testEnginePillIsNilWhenNeitherHalfIsKnown() throws {
        XCTAssertNil(SleepHistoryPresentation.enginePill(try entry()))
    }

    // MARK: dateText

    func testDateTextFormatsTheGitShortDate() {
        XCTAssertEqual(SleepHistoryPresentation.dateText("2026-09-01"), "Sep 1")
    }

    func testDateTextFallsBackToTheRawStringWhenUnparseable() {
        XCTAssertEqual(SleepHistoryPresentation.dateText("not-a-date"), "not-a-date")
    }

    /// P4: git renders `--date=iso-strict` in the COMMIT's zone. The parser reads
    /// the offset for real and displays in the reader's zone; the tests pin a zone
    /// so they never depend on the runner's locale.
    func testDateAndTimeReadAnIsoStrictStampInTheGivenZone() {
        let utc = TimeZone(identifier: "UTC")!
        XCTAssertEqual(SleepHistoryPresentation.dateText("2026-09-05T21:41:00+00:00", timeZone: utc), "Sep 5")
        XCTAssertEqual(SleepHistoryPresentation.timeText("2026-09-05T21:41:00+00:00", timeZone: utc), "9:41 PM")
        let plus2 = TimeZone(secondsFromGMT: 7200)!
        XCTAssertEqual(SleepHistoryPresentation.timeText("2026-09-05T21:41:00+00:00", timeZone: plus2), "11:41 PM")
    }

    /// A legacy `--date=short` value (a cached snapshot, or an older backend) has
    /// no time — `—`, never a fabricated midnight (R-A14).
    func testTimeTextIsADashForALegacyDateOnlyValue() {
        XCTAssertEqual(SleepHistoryPresentation.timeText("2026-09-01"), "—")
        XCTAssertEqual(SleepHistoryPresentation.timeText("not-a-date"), "—")
    }
}
