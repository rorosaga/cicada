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
}
