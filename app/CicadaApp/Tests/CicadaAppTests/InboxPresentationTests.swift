import XCTest
@testable import CicadaApp

/// G115 Phase 1 — the pure half of the card: cause line, age phrase, bolded
/// excerpt ranges, and the collapse rule that closes the owner's "list of
/// URLs that doesn't end" defect (2026-09-03).
final class InboxPresentationTests: XCTestCase {

    private func decode(_ json: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    func testDecodesCauseAndNewFieldsAndToleratesTheirAbsence() throws {
        let item = try decode("""
        {"id":"inbox-001","kind":"decay","requiredInput":"choice","title":"t","body":"b",
         "entityType":"project","sourceEpisode":"ep_2026-08-20_001","recommendedKey":"archive",
         "extractorConfidence":0.3,"informational":false,
         "cause":{"episodeId":"ep_2026-08-20_001","timestamp":"2026-08-20T10:00:00+00:00",
                  "conversationId":"ses_x","harness":"claude-code","origin":"claude-code",
                  "conversationTitle":"Parser planning","excerpt":"user: alpha-project is the parser",
                  "mentionOffsets":[[6,19]],"start":0,"end":33,"tier":"entity","spanKind":"derived"},
         "options":[{"key":"archive","label":"Archive","recommended":true,"verdict":"agreed"},
                    {"key":"keep","label":"Keep active","verdict":"overruled"}]}
        """)
        XCTAssertEqual(item.entityType, "project")
        XCTAssertEqual(item.cause?.tier, "entity")
        XCTAssertEqual(item.cause?.mentionOffsets, [[6, 19]])
        XCTAssertEqual(item.recommendedKey, "archive")
        XCTAssertTrue(item.options[0].recommended)
        XCTAssertFalse(item.options[1].recommended)
        XCTAssertEqual(item.options[1].verdict, "overruled")
        XCTAssertEqual(item.recommendedIndex, 0)

        let legacy = try decode("""
        {"id":"inbox-002","kind":"conflict","requiredInput":"choice","title":"t","body":"b",
         "options":[{"key":"a","label":"x"}]}
        """)
        XCTAssertNil(legacy.cause)
        XCTAssertFalse(legacy.informational)
        XCTAssertFalse(legacy.options[0].recommended)
        XCTAssertNil(legacy.recommendedIndex)
    }

    func testCauseLineReadsFromTitleHarnessAndAge() throws {
        let item = try decode("""
        {"id":"i","kind":"conflict","requiredInput":"choice","title":"t","body":"b",
         "cause":{"conversationTitle":"Parser planning","harness":"claude-code",
                  "timestamp":"2026-08-20T10:00:00+00:00","excerpt":"x","tier":"item"}}
        """)
        let now = ISO8601DateFormatter().date(from: "2026-08-30T10:00:00Z")!
        XCTAssertEqual(item.causeLine(now: now), "From “Parser planning” · claude-code · 10 days ago")
        let none = try decode("""
        {"id":"j","kind":"decay","requiredInput":"choice","title":"t","body":"b",
         "cause":{"excerpt":"[ no source recorded ]","tier":"none"}}
        """)
        XCTAssertEqual(none.causeLine(now: now), "[ no source recorded ]")
        XCTAssertFalse(none.hasCause)
        let missing = try decode("""
        {"id":"k","kind":"decay","requiredInput":"choice","title":"t","body":"b"}
        """)
        XCTAssertEqual(missing.causeLine(now: now), "[ no source recorded ]")
    }

    func testAgePhraseMatchesTheServer() {
        XCTAssertEqual(InboxAge.phrase(days: nil), "unknown")
        XCTAssertEqual(InboxAge.phrase(days: 0), "today")
        XCTAssertEqual(InboxAge.phrase(days: 1), "yesterday")
        XCTAssertEqual(InboxAge.phrase(days: 3), "3 days ago")
        XCTAssertEqual(InboxAge.phrase(days: 21), "3 weeks ago")
        // Parity, not prettiness: `humanize_age` only reaches the week branch at
        // 14 days and the month branch at 60, so a 7-day-old item reads "7 days
        // ago" and a 35-day-old one "5 weeks ago" on BOTH surfaces. The plan's
        // draft asserted "a week ago" here (and "a month ago" at 30) — corrected
        // to what the server actually says, because a card and an MCP blurb
        // disagreeing about the same item is the defect this test exists to
        // prevent. Consequence of those boundaries, asserted so a later "tidy
        // up" does not silently change the wording on one surface only: the
        // singular "a week ago"/"a month ago" branches are unreachable — 1 week
        // needs < 14 days and 1 month needs < 60, and both are excluded.
        XCTAssertEqual(InboxAge.phrase(days: 7), "7 days ago")
        XCTAssertEqual(InboxAge.phrase(days: 193), "6 months ago")
        XCTAssertEqual(InboxAge.phrase(days: 30), "4 weeks ago")
        XCTAssertEqual(InboxAge.phrase(days: 35), "5 weeks ago")
        XCTAssertEqual(InboxAge.phrase(days: 60), "2 months ago")
        // The half-way case, where Python's banker's rounding and Swift's
        // default `.rounded()` disagree: 75/30 == 2.5 → 2, not 3.
        XCTAssertEqual(InboxAge.phrase(days: 75), "2 months ago")
        XCTAssertEqual(InboxAge.phrase(days: 105), "4 months ago")
        XCTAssertEqual(InboxAge.phrase(days: 400), "a year ago")
        XCTAssertEqual(InboxAge.phrase(days: 1100), "3 years ago")
        let now = ISO8601DateFormatter().date(from: "2026-08-30T10:00:00Z")!
        XCTAssertEqual(InboxAge.days(since: "2026-08-20T10:00:00+00:00", now: now), 10)
        XCTAssertEqual(InboxAge.days(since: "2026-08-27", now: now), 3)
        XCTAssertNil(InboxAge.days(since: "nope", now: now))
    }

    func testExcerptBoldsExactlyTheMentionUsingScalarOffsets() {
        let text = "café: alpha-project is the parser"
        let attributed = ExcerptText.attributed(text, bold: [[6, 19]])
        var bold: [String] = []
        for run in attributed.runs where run.inlinePresentationIntent == .stronglyEmphasized {
            bold.append(String(attributed[run.range].characters))
        }
        XCTAssertEqual(bold, ["alpha-project"])
        // out-of-range offsets never crash and bold nothing
        let safe = ExcerptText.attributed("short", bold: [[3, 99], [-1, 2]])
        XCTAssertTrue(safe.runs.allSatisfy { $0.inlinePresentationIntent != .stronglyEmphasized })
    }

    func testCollapsedLinesShowsThreeAndCountsTheRest() {
        let five = CollapsedLines("https://example.com/1\nhttps://example.com/2\n\nhttps://example.com/3\nhttps://example.com/4\nhttps://example.com/5")
        XCTAssertEqual(five.lines.count, 5)
        XCTAssertTrue(five.needsCollapse)
        XCTAssertEqual(five.head.count, 3)
        XCTAssertEqual(five.hidden, 2)
        let four = CollapsedLines("a\nb\nc\nd")
        XCTAssertFalse(four.needsCollapse, "four lines are not worth a toggle")
        XCTAssertEqual(four.head.count, 4)
        XCTAssertEqual(CollapsedLines("").lines, [])
    }
}
