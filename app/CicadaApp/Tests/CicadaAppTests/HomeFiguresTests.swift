import XCTest
@testable import CicadaApp

/// Track I part b T9 (design §6.3, R-IB9) — every number on Home, as a pure
/// function of what the Store already holds. Placeholders only.
final class HomeFiguresTests: XCTestCase {
    private let today = ISO8601DateFormatter().date(from: "2026-09-23T12:00:00Z")!

    private func row(_ id: String, _ label: String, mark: String, today n: Int, yesterday y: Int = 0) -> SourceOverview {
        SourceOverview(id: id, label: label, kind: .harness, mark: mark,
                       activity: ["2026-09-23": n, "2026-09-22": y].filter { $0.value > 0 })
    }

    func testTodaySumsOnlyTodaysUTCBucketAndNamesTheTopThree() {
        let t = HomeFigures.today([
            row("harness:claude-code", "Claude Code", mark: "claude-code", today: 6, yesterday: 40),
            row("chrome-bookmarks", "Chrome", mark: "chrome-bookmark", today: 5),
            row("chat-export:chatgpt", "ChatGPT export", mark: "chatgpt-export", today: 2),
            row("rss", "RSS", mark: "rss", today: 1),
            row("telegram", "Telegram", mark: "telegram", today: 0),
        ], today: today)
        XCTAssertEqual(t.captured, 14, "yesterday's 40 never leaks into today")
        XCTAssertEqual(t.origins.map(\.sourceId), ["harness:claude-code", "chrome-bookmarks", "chat-export:chatgpt"])
    }

    func testTodayIsUnknownUntilTheSnapshotLoads() {
        XCTAssertNil(HomeFigures.today(nil, today: today).captured, "never a guessed 0 (R-A14)")
        XCTAssertEqual(HomeFigures.today([], today: today).captured, 0)
    }

    func testNeedsYouShowsTheFirstThreeInTheInboxsOwnOrder() {
        let items = (1...5).map { FindFixtures.inbox("inbox-00\($0)", question: "Still tracking alpha-project \($0)?") }
        let n = HomeFigures.needsYou(items)
        XCTAssertEqual(n.shown.map(\.id), ["inbox-001", "inbox-002", "inbox-003"])
        XCTAssertEqual(n.total, 5)
    }

    private func entry(_ hash: String, kind: String = "sleep", files: [String] = [],
                       created: Int = 0, updated: Int = 0) throws -> SleepHistoryEntry {
        let object: [String: Any] = ["commitHash": hash, "date": "2026-09-22", "message": "Sleep cycle", "kind": kind,
                                     "filesChanged": files, "entitiesCreated": created, "entitiesUpdated": updated]
        return try JSONDecoder().decode(SleepHistoryEntry.self, from: JSONSerialization.data(withJSONObject: object))
    }

    func testLastReadIsTheNewestSleepCommitNeverADecayOrInboxOne() throws {
        let decay = try entry("d1", kind: "decay"), sleep = try entry("s1"), older = try entry("s0")
        XCTAssertEqual(HomeFigures.lastRead([decay, sleep, older], loaded: true, hasRunBefore: true, lastSleepAt: nil),
                       .entry(sleep))
        XCTAssertEqual(HomeFigures.lastRead([], loaded: false, hasRunBefore: nil, lastSleepAt: nil), .loading,
                       "history is not disk-cached — '—' until it lands")
        XCTAssertEqual(HomeFigures.lastRead([], loaded: true, hasRunBefore: false, lastSleepAt: nil), .never)
    }

    /// I-b final review, finding 5 — the history page is the newest 15 commits,
    /// inbox answers included: a read pushed off it is not "Nothing read yet".
    func testALastReadOffTheHistoryPageIsNeverNothingReadYet() throws {
        let decay = try entry("d1", kind: "decay"), inbox = try entry("i1", kind: "inbox")
        XCTAssertEqual(HomeFigures.lastRead([decay], loaded: true, hasRunBefore: nil, lastSleepAt: nil), .earlier(nil),
                       "a decay commit only exists because a Sleep ran")
        XCTAssertEqual(HomeFigures.lastRead(Array(repeating: inbox, count: 15), loaded: true,
                                            hasRunBefore: true, lastSleepAt: "2026-09-20T03:00:00Z"),
                       .earlier("2026-09-20T03:00:00Z"))
        XCTAssertEqual(HomeFigures.lastRead([inbox], loaded: true, hasRunBefore: nil, lastSleepAt: nil), .loading,
                       "the status not yet known is never a guess either way")
    }

    func testLastReadLineStatesTheDayAndOnlyTheCountsThatHappened() throws {
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(HomeFigures.lastReadLine(try entry("s1", created: 9, updated: 1_024), locale: en),
                       "Sep 22 · 9 new · 1,024 updated")
        XCTAssertEqual(HomeFigures.lastReadLine(try entry("s2", updated: 3), locale: en), "Sep 22 · 3 updated")
        XCTAssertEqual(HomeFigures.lastReadLine(try entry("s3"), locale: en), "Sep 22 · nothing changed")
    }

    func testChipsAreEntityPagesThatStillExistInTheGraph() throws {
        let e = try entry("s1", files: ["entities/alpha-project.md", "entities/bob-example.md", "inbox/inbox-001.md",
                                        "entities/gone-page.md", "entities/alpha-project.md",
                                        "entities/gamma.md", "entities/delta.md"])
        let nodes = [FindFixtures.node("alpha-project", "alpha-project"),
                     FindFixtures.node("bob-example", "bob-example", type: .person),
                     FindFixtures.node("gamma", "gamma-example"), FindFixtures.node("delta", "delta-example")]
        let chips = HomeFigures.chips(e, nodes: nodes)
        XCTAssertEqual(chips.shown.map(\.id), ["alpha-project", "bob-example", "gamma"])
        XCTAssertEqual(chips.more, 1, "a deleted page is never a chip, and a repeat counts once")
    }
}
