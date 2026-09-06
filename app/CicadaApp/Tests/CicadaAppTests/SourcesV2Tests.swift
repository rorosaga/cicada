import XCTest
@testable import CicadaApp

/// Track S (R-S1 … R-S4). Every decision the Sources grid makes is a pure
/// function with a table test, so the card can be a renderer and a reviewer
/// can read the rule instead of the layout.
final class SourcesV2Tests: XCTestCase {

    // MARK: SourceLiveness (R-S2 — the green dot meant four things, D1/D2)

    private func row(_ id: String, kind: SourceKind = .import, actions: [String] = [],
                     harness: String? = nil, channelId: String? = nil,
                     lastError: String? = nil, last: String? = nil) -> SourceOverview {
        SourceOverview(id: id, label: id, kind: kind, mark: id, episodes: 1,
                       lastActivityAt: last, connected: true, lastError: lastError,
                       actions: actions, channelId: channelId, harness: harness)
    }

    func testLivenessNamesEveryStateTheCatalogCanProduce() {
        // A watched browser: the watch wins over the channel's actions.
        XCTAssertEqual(SourceLiveness.of(row: row("chrome-bookmarks", kind: .browser,
                                                  actions: ["sync"], channelId: "chrome-bookmarks"),
                                         channel: nil, watch: .watching).state, .watching)
        XCTAssertEqual(SourceLiveness.of(row: row("chrome-bookmarks", actions: ["sync"]),
                                         channel: nil, watch: .stale).state, .behind)
        XCTAssertEqual(SourceLiveness.of(row: row("chrome-bookmarks", actions: ["sync"]),
                                         channel: nil, watch: .syncing).state, .syncing)
        // A hook-captured harness: no channel, `harness` set.
        XCTAssertEqual(SourceLiveness.of(row: row("harness:claude-code", kind: .harness,
                                                  harness: "claude-code"),
                                         channel: nil, watch: nil).state, .captured)
        // A chat export is `kind: .harness` with NO harness and one action.
        XCTAssertEqual(SourceLiveness.of(row: row("chat-export:claude", kind: .harness,
                                                  actions: ["import"], channelId: "chat-export:claude"),
                                         channel: nil, watch: nil).state, .imported)
        XCTAssertEqual(SourceLiveness.of(row: row("rss", kind: .feed, actions: ["poll", "manage"],
                                                  channelId: "rss"),
                                         channel: nil, watch: nil).state, .pollsNightly)
        XCTAssertEqual(SourceLiveness.of(row: row("notes", actions: ["sync"], channelId: "notes"),
                                         channel: nil, watch: nil).state, .syncsOnDemand)
        // The open `origin:<id>` family has no channel and no harness.
        XCTAssertEqual(SourceLiveness.of(row: row("origin:unknown"), channel: nil, watch: nil).state,
                       .imported)
    }

    func testAFailureOutranksEveryHealthyStateAndPutsItsFirstClauseOnTheCard() {
        let broken = row("pinterest", actions: ["sync", "disconnect"], channelId: "pinterest",
                         lastError: "Can't read the file. Grant Full Disk Access in System Settings.")
        let liveness = SourceLiveness.of(row: broken, channel: nil, watch: nil)
        XCTAssertEqual(liveness.state, .failed)
        XCTAssertEqual(liveness.detail, "Can't read the file")
        XCTAssertTrue(liveness.verb.contains("Can't read the file"), "D2 — the reason is ON the card")
        XCTAssertEqual(liveness.tone, .danger)
        // `.blocked` is the one failure with a fix, so it keeps its own state.
        XCTAssertEqual(SourceLiveness.of(row: broken, channel: nil, watch: .blocked).state, .blocked)
    }

    func testFirstClauseCutsOnTheFirstBoundaryAndNeverRunsLong() {
        XCTAssertEqual(SourceLiveness.firstClause(of: "Sync failed · HTTP 401"), "Sync failed")
        XCTAssertEqual(SourceLiveness.firstClause(of: "No network. Try again later."), "No network")
        XCTAssertEqual(SourceLiveness.firstClause(of: "  padded  "), "padded")
        XCTAssertNil(SourceLiveness.firstClause(of: "   "))
        let long = String(repeating: "x", count: 200)
        XCTAssertLessThanOrEqual(SourceLiveness.firstClause(of: long)?.count ?? 0,
                                 SourceLiveness.maxClauseLength)
    }

    func testEveryLivenessStateHasANonEmptyVerbAndNoStateReadsAsAnother() {
        let verbs = SourceLiveness.State.allCases.map {
            SourceLiveness(state: $0, detail: nil).verb
        }
        XCTAssertTrue(verbs.allSatisfy { !$0.isEmpty })
        XCTAssertEqual(Set(verbs).count, verbs.count, "two states must never print the same verb")
    }

    // MARK: SourceDisplayName (R-S4 — A1/A2/A3/A4)

    func testDisplayNameIsABrandForEveryCatalogRow() {
        let expected: [String: String] = [
            "chat-export:claude": "Claude export", "chat-export:chatgpt": "ChatGPT export",
            "chat-export:gemini": "Gemini export", "chrome-bookmarks": "Chrome",
            "safari-bookmarks": "Safari", "safari-tabs": "Safari tabs", "pinterest": "Pinterest",
            "reddit": "Reddit", "x": "X", "instagram": "Instagram", "youtube": "YouTube",
            "linkedin": "LinkedIn", "tiktok": "TikTok", "rss": "RSS", "calendar": "Calendars",
            "telegram": "Telegram", "notes": "Apple Notes", "files": "Files & links",
        ]
        for (id, name) in expected {
            XCTAssertEqual(SourceDisplayName.of(SourceOverview(id: id, label: "\(id) bookmarks",
                                                               kind: .import)), name)
        }
    }

    func testDisplayNameNeverPrintsARawIdAQuestionMarkOrACapitalizedAcronym() {
        func name(_ id: String, label: String) -> String {
            SourceDisplayName.of(SourceOverview(id: id, label: label, kind: .import))
        }
        XCTAssertEqual(name("origin:unknown", label: "unknown"), "Unattributed")
        XCTAssertEqual(name("origin:bookmark", label: "bookmark"), "Saved links")
        XCTAssertEqual(name("origin:url", label: "url"), "Links")
        XCTAssertEqual(name("origin:rss-mirror", label: "rss-mirror"), "RSS mirror")
        XCTAssertEqual(name("harness:unknown", label: "Other agents"), "Other agents")
        XCTAssertEqual(name("harness:cursor", label: "Cursor"), "Cursor")
        // Sentence case, not title case — see the fallback rule below.
        XCTAssertEqual(name("harness:brand-new", label: "brand-new"), "Brand new")
        for id in ["origin:unknown", "origin:url", "harness:unknown", "origin:mystery"] {
            let n = name(id, label: id)
            XCTAssertFalse(n.contains("?"), "\(id) → \(n)")
            XCTAssertFalse(n.first?.isLowercase ?? true, "\(id) → \(n)")
        }
    }

    /// A1: the name has to survive a 1.4× zoom in a two-column window, so the
    /// brand is short by construction, not by truncation.
    func testEveryDisplayNameFitsOnOneLine() {
        for id in SourceDisplayName.pinnedIds {
            let n = SourceDisplayName.of(SourceOverview(id: id, label: id, kind: .import))
            XCTAssertLessThanOrEqual(n.count, 16, "\(id) → \(n)")
        }
    }

    // MARK: SourceGridColumns (R-S1 — C2/C3)

    func testColumnCountIsClampedAndShrinksWhenTheChromeIsZoomed() {
        XCTAssertEqual(SourceGridColumns.count(width: 640, scale: 1.0), 2)
        XCTAssertEqual(SourceGridColumns.count(width: 1200, scale: 1.0), 4)
        XCTAssertEqual(SourceGridColumns.count(width: 1200, scale: 1.4), 3)
        XCTAssertEqual(SourceGridColumns.count(width: 300, scale: 1.0), 2, "floor is 2, never 1")
        XCTAssertEqual(SourceGridColumns.count(width: 4000, scale: 1.0), 4, "ceiling is 4")
        XCTAssertEqual(SourceGridColumns.count(width: 0, scale: 1.0), 2, "a zero width never crashes")
    }

    // MARK: SourceDeltaText (R-S3 — two nouns, D3)

    func testDeltaNamesCapturesAndSaysWhenNothingIsNew() {
        let en = Locale(identifier: "en_US")
        let today = ISO8601DateFormatter().date(from: "2026-09-05T00:00:00Z")!
        // The sentence's window is `points.count`, never a second constant, so
        // the fixture is a real 14-day series — not four buckets claiming 14.
        let fortnight = [1, 0, 5, 6] + Array(repeating: 0, count: 10)
        XCTAssertEqual(SourceDeltaText.text(points: fortnight, lastActivity: today,
                                            today: today, locale: en),
                       "+12 captured in 14 days")
        XCTAssertEqual(SourceDeltaText.text(points: Array(repeating: 1, count: 7),
                                            lastActivity: today, today: today, locale: en),
                       "+7 captured in 7 days", "the window is the array, not a constant")
        let june = ISO8601DateFormatter().date(from: "2026-06-14T00:00:00Z")!
        XCTAssertEqual(SourceDeltaText.text(points: [0, 0, 0], lastActivity: june,
                                            today: today, locale: en),
                       "Nothing new since June")
        XCTAssertEqual(SourceDeltaText.text(points: [], lastActivity: nil, today: today,
                                            locale: en),
                       "Nothing captured yet")
    }

    // MARK: UsageFormat.count (R-S5/R-S17 — one formatter, the reader's locale)

    /// B1 — three formatting conventions shared one window: the card grid said
    /// "1,035 entities" (`UsageFormat.count` pinned `en_US_POSIX`) while
    /// Contributors, eight inches below, said "1.035 files" (a
    /// `LocalizedStringKey` interpolation, grouped in the VIEWER's locale).
    /// Neither half was right: one was consistent and locale-wrong, the other
    /// locale-right and inconsistent. One formatter, the viewer's locale,
    /// everywhere — and an explicit parameter so both answers are assertable on
    /// any host rather than asserting the tester's own Mac.
    ///
    /// **The second locale is `de_DE`, not the `es_ES` the ruling sketched, and
    /// that is deliberate.** CLDR gives `es_ES` `minimumGroupingDigits = 2`, so
    /// Spanish does not group a FOUR-digit number at all: `count(1927, es_ES)`
    /// is "1927", and asserting "1.927" there fails against ICU, not against
    /// this code. The defect R-S17 names is real — it is just German and French
    /// readers who saw the wrong separator on a four-digit count, not Spanish
    /// ones. Both rules are pinned below so the next reader does not "correct"
    /// the surprising one back into a bug report.
    func testCountFollowsTheViewersLocaleAndIsAssertableInBoth() {
        XCTAssertEqual(UsageFormat.count(1927, locale: Locale(identifier: "en_US")), "1,927")
        XCTAssertEqual(UsageFormat.count(1927, locale: Locale(identifier: "de_DE")), "1.927")
        XCTAssertEqual(UsageFormat.count(0, locale: Locale(identifier: "en_US")), "0")
        // es_ES: four digits ungrouped, seven digits grouped — the formatter
        // follows the locale's own rule instead of imposing one.
        XCTAssertEqual(UsageFormat.count(1927, locale: Locale(identifier: "es_ES")), "1927")
        XCTAssertEqual(UsageFormat.count(1_284_000, locale: Locale(identifier: "es_ES")), "1.284.000")
        // A card and a contributor row must produce the IDENTICAL string.
        let card = SourceOverview(id: "x", label: "X", kind: .browser, items: 1927)
        XCTAssertEqual(UsageFormat.count(card.headline!.count, locale: Locale(identifier: "de_DE")),
                       UsageFormat.count(1927, locale: Locale(identifier: "de_DE")))
    }

    /// `IntegrationRowState.line` is a `parts.append("...")`, not a `Text("...")`,
    /// so R-S18's needle cannot see it — this is the assertion that holds it
    /// instead. Settings → Integrations composes the same count as the Sources
    /// grid, and the two must group identically or B1 is back one tab over.
    func testTheIntegrationsRowCountsInTheSameFormatterAsTheGrid() {
        let channel = SourceChannel(id: "chrome-bookmarks", label: "Chrome bookmarks",
                                    connected: true, count: 1927)
        let de = Locale(identifier: "de_DE")
        XCTAssertTrue(IntegrationRowState.line(channel, locale: de).contains("1.927 items"),
                      "the Integrations row groups exactly as the grid does")
        XCTAssertTrue(IntegrationRowState.line(channel, locale: de)
                        .contains("\(UsageFormat.count(1927, locale: de)) items"))
        let one = SourceChannel(id: "rss", label: "RSS", connected: true, count: 1)
        XCTAssertTrue(IntegrationRowState.line(one, locale: de).contains("1 item"),
                      "the singular keeps its noun singular")
    }

    // MARK: Task 6 — the header's `+ Add a source` and the detail page's own
    // header card (R-S7 / R-S9)

    /// Reads a file under `Sources/CicadaApp/`, resolved from this test file's
    /// own path (the `FixWaveTests.sourceFile(_:)` pattern) so it works from any
    /// working directory.
    private func sourceFile(_ relativePath: String) throws -> String {
        let packageRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp package root
        return try String(contentsOf: packageRoot
            .appendingPathComponent("Sources/CicadaApp")
            .appendingPathComponent(relativePath), encoding: .utf8)
    }

    /// F2/R-S7 — `+ Add a source` has to exist on a POPULATED page, not only in
    /// the empty state. A rendered-view test cannot see "the button is only in
    /// the `rows.isEmpty` branch", so this reads the source.
    func testAddASourceLivesInTheHeaderAndIsPresentedExactlyOnce() throws {
        let page = try sourceFile("Views/Sources/SourcesPageView.swift")
        XCTAssertTrue(page.contains("Add a source"),
                      "the header lost its affordance — F2 all over again")
        XCTAssertEqual(page.components(separatedBy: "AddSourceSheet(").count - 1, 1,
                       "exactly one presenter of the sheet on this page")
        XCTAssertTrue(page.contains("initialTile: nil"),
                      "R-S9 — the header opens the catalog ROOT, not a staged tile")
        XCTAssertFalse(page.contains("routeToFeedAddSource"),
                       "R-S9 — no bounce to the Feed tab just to show a sheet")
    }

    /// R-S7 — the empty state keeps the affordance it already has. R-S9's fix is
    /// that the page never *loses* a way in, not that both ways be identical, so
    /// a reviewer removing `EmptyStateView`'s action "because the header has one
    /// now" is a regression, not a tidy-up.
    func testTheEmptyStateKeepsItsOwnWayIn() throws {
        let grid = try sourceFile("Views/Sources/SourceCardGrid.swift")
        XCTAssertTrue(grid.contains("actionLabel: \"Add a source\""))
        XCTAssertTrue(grid.contains("settingsSection: .integrations"))
    }

    /// The detail page's window is the backend's OWN `ACTIVITY_DAYS`
    /// (`api/services/source_overview.py:34` — 30), not a second number. Asking
    /// Track A's window for 30 days on a payload that only carries 14 keys reads
    /// as leading zeros, never a crash — the shape `MemorySourcesTests` already
    /// pins for the 14-day case.
    func testTheDetailWindowIsTheBackendsThirtyDaysAndSurvivesAShortPayload() {
        XCTAssertEqual(SourceCardMetrics.detailSparkDays, 30,
                       "the detail sparkline covers the whole payload the backend ships")
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let today = calendar.date(from: DateComponents(year: 2026, month: 9, day: 5, hour: 12))!
        let points = sparklinePoints(activity: ["2026-09-05": 4, "2026-08-30": 1],
                                     days: SourceCardMetrics.detailSparkDays, today: today)
        XCTAssertEqual(points.count, 30)
        XCTAssertEqual(Array(points.prefix(20)), Array(repeating: 0, count: 20))
        XCTAssertEqual(points.last, 4)
        XCTAssertEqual(points.reduce(0, +), 5)
        // R-S3's two nouns, on the wider window: the delta names CAPTURES and
        // takes its span from the array, so the sentence under a 30-day line can
        // never claim 14 days.
        XCTAssertEqual(SourceDeltaText.text(points: points, lastActivity: nil, today: today,
                                            locale: Locale(identifier: "en_US")),
                       "+5 captured in 30 days")
    }

    /// R-S19 — the detail header sets the SAME two nouns the grid card does:
    /// the total is `headline`'s own unit, the line and the delta are captures.
    /// One projection, two renderings; a second `switch` on `kind` in the header
    /// card is how a browser's 506 items become 506 "captures" one page over.
    func testTheHeaderCardReadsTheSameTwoNounsAsTheGridCard() throws {
        let card = try sourceFile("Views/Sources/SourceHeaderCard.swift")
        XCTAssertTrue(card.contains("source.headline"),
                      "the total is `headline`, not a re-derived count")
        XCTAssertTrue(card.contains("SourceDeltaText.text("),
                      "the delta is the grid's own sentence, not a second one")
        XCTAssertFalse(card.contains("switch source.kind"),
                       "R-S19 — the header must not re-decide the unit")
        let browser = SourceOverview(id: "chrome-bookmarks", label: "Chrome bookmarks",
                                     kind: .browser, items: 506)
        XCTAssertEqual(browser.headline?.noun, "item")
    }

    /// D2, one page in: the card prints the error's first clause because it has
    /// one line; the detail page has the room for the whole message, so it says
    /// the whole message. Both read the SAME `verb`, so the two surfaces can
    /// never name a failure differently.
    func testTheDetailSentenceCarriesTheWholeErrorWhereTheCardCarriesAClause() {
        let long = "Can't read the file. Grant Full Disk Access in System Settings, then sync again."
        let broken = row("pinterest", actions: ["sync"], channelId: "pinterest", lastError: long)
        let liveness = SourceLiveness.of(row: broken, channel: nil, watch: nil)
        XCTAssertEqual(liveness.verb, "Sync failed — Can't read the file")
        let sentence = SourceHeaderCard.sentence(liveness: liveness, fullError: long)
        XCTAssertTrue(sentence.contains(long), "the detail page shows the WHOLE error")
        XCTAssertTrue(sentence.hasPrefix("Sync failed"), "and names the same state as the card")
        // A healthy source has no error to expand, so the sentence IS the verb.
        let healthy = SourceLiveness.of(row: row("rss", actions: ["poll"]), channel: nil, watch: nil)
        XCTAssertEqual(SourceHeaderCard.sentence(liveness: healthy, fullError: nil), healthy.verb)
        XCTAssertEqual(SourceHeaderCard.sentence(liveness: healthy, fullError: "   "), healthy.verb,
                       "a blank error is no error — never a dangling em dash")
    }
}
