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

    // MARK: - DS-2 (R-DI12, R-DI15, R-DI22)

    private let us = Locale(identifier: "en_US")
    private let utc = TimeZone(identifier: "UTC")!

    private func item(_ json: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    private func caused(_ cause: String, extra: String = "") throws -> InboxItem {
        try item(#"{"id":"inbox-001","kind":"conflict","requiredInput":"choice","title":"t"\#(extra),"cause":\#(cause)}"#)
    }

    func testCompactAgesShareThePhrasesBoundaries() {
        XCTAssertEqual([0, 1, 5, 13, 14, 20, 59, 60, 193, 364, 365, 800].map(InboxAge.compact(days:)),
                       ["today", "1d", "5d", "13d", "2w", "3w", "8w", "2mo", "6mo", "12mo", "1y", "2y"])
    }

    func testTheSourceLineNamesAConversationTheWayAPersonWould() throws {
        let titled = try caused(#"{"episodeId":"ep_2026-08-25_001","timestamp":"2026-08-25T10:00:00Z","harness":"claude-code","conversationTitle":"Index choice","excerpt":"x","tier":"claim"}"#)
        XCTAssertEqual(InboxSourceLine.full(titled, locale: us, timeZone: utc), "Claude Code · Index choice · Aug 25")
        XCTAssertEqual(InboxSourceLine.row(titled, locale: us, timeZone: utc), "Claude Code · Aug 25")
        XCTAssertEqual(InboxSourceLine.help(titled), "Episode ep_2026-08-25_001")
        XCTAssertEqual(InboxSourceLine.markOrigin(titled), "claude-code")

        let untitled = try caused(#"{"episodeId":"ep_2026-08-25_001","timestamp":"2026-08-25T10:00:00Z","harness":"claude-code","excerpt":"x","tier":"claim"}"#)
        XCTAssertEqual(InboxSourceLine.full(untitled, locale: us, timeZone: utc), "a Claude Code conversation · Aug 25")

        let exported = try caused(#"{"episodeId":"ep_2026-05-02_003","timestamp":"2026-05-02T09:00:00Z","origin":"chatgpt-export","conversationTitle":"Planning","excerpt":"x","tier":"entity"}"#)
        XCTAssertEqual(InboxSourceLine.full(exported, locale: us, timeZone: utc), "ChatGPT · Planning · May 2")

        let none = try caused(#"{"excerpt":"[ no source recorded ]","tier":"none"}"#)
        XCTAssertEqual(InboxSourceLine.full(none), "[ no source recorded ]", "DR-55 — served exactly as written")
        XCTAssertEqual(InboxSourceLine.row(none), "[ no source recorded ]")
        XCTAssertNil(InboxSourceLine.help(none))

        for line in [InboxSourceLine.full(titled), InboxSourceLine.row(titled), InboxSourceLine.full(untitled)] {
            XCTAssertFalse(line.contains("ep_") || line.contains("claude-code"), "DR-54: \(line)")
        }
    }

    func testTheRowAgeIsCompactWithTheDayInHelpAndADashWithItsReason() throws {
        let now = ISO8601DateFormatter().date(from: "2026-09-22T10:00:00Z")!
        let titled = try caused(#"{"episodeId":"ep_2026-08-25_001","timestamp":"2026-08-25T10:00:00Z","harness":"claude-code","excerpt":"x","tier":"claim"}"#)
        let age = InboxRowAge.of(titled, now: now, locale: us, timeZone: utc)
        XCTAssertEqual(age.text, "4w")
        XCTAssertEqual(age.help, "Aug 25, 2026")
        let none = try caused(#"{"excerpt":"[ no source recorded ]","tier":"none"}"#)
        XCTAssertEqual(InboxRowAge.of(none, now: now).text, "—")
        XCTAssertEqual(InboxRowAge.of(none, now: now).help, Copy.Inbox.noSourceAge)
    }

    /// DR-56 / R-DI22 — clean per segment: markers and wikilinks go, a segment's edges stay.
    func testTheExcerptIsCleanTextAndKeepsItsEdges() {
        XCTAssertEqual(ExcerptText.clean("# Episode 12\n- swapped the store"), "Episode 12 swapped the store")
        XCTAssertEqual(ExcerptText.clean("see [[alpha-project-notes]] now"), "see Alpha Project Notes now")
        XCTAssertEqual(ExcerptText.clean("[[alpha-project|Alpha]] and > quoted"), "Alpha and > quoted")
        XCTAssertEqual(ExcerptText.clean("> a quote\n\n  and more  "), "a quote and more ")
        XCTAssertEqual(ExcerptText.clean(" so anomaly"), " so anomaly", "never trims — it would glue the segments")
        XCTAssertEqual(ExcerptText.clean(" - 3 more", atLineStart: false), " - 3 more", "a mid-line segment keeps its minus")
        XCTAssertEqual(ExcerptText.clean("see [[alpha-project|"), "see ", "a link the mention split leaves no brackets")
        XCTAssertEqual(ExcerptText.clean("]] and on"), " and on")
    }

    /// R-DI18 / DR-53 — every kind glyph is an outline symbol; the hue alone carries the kind (DR-8).
    func testKindGlyphsAreOutlineSymbols() {
        let kinds: [InboxKind] = [.decay, .conflict, .clarification, .mergeSuggestion, .divergence, .normalization,
                                  .removal, .followup, .unknown]
        XCTAssertEqual(kinds.filter { $0.icon.hasSuffix(".fill") }, [])
    }

    /// R-DI11 — an asserted G118 span is washed; a mention found by name is semibold and says so.
    func testTheQuoteWashesOnlyWhatWasQuoted() throws {
        let asserted = try caused(#"{"episodeId":"ep_1","excerpt":"Discussed swapping the store","mentionOffsets":[[10,18]],"start":0,"tier":"claim","spanKind":"asserted"}"#)
        XCTAssertEqual(QuoteSegments.of(asserted), [.init(text: "Discussed ", mark: .plain),
                                                    .init(text: "swapping", mark: .current),
                                                    .init(text: " the store", mark: .plain)])
        XCTAssertFalse(QuoteSegments.isDerived(asserted))
        let derived = try caused(#"{"episodeId":"ep_1","excerpt":"Discussed swapping the store","mentionOffsets":[[10,18]],"start":0,"tier":"claim","spanKind":"derived"}"#)
        XCTAssertEqual(QuoteSegments.of(derived)?[1], .init(text: "swapping", mark: .mention))
        XCTAssertTrue(QuoteSegments.isDerived(derived))
        let none = try caused(#"{"excerpt":"[ no source recorded ]","tier":"none"}"#)
        XCTAssertNil(QuoteSegments.of(none), "no source → no quote block at all")
    }

    func testTheGuessIsTheExtractorsAndNeverOnAnInformationalCard() throws {
        XCTAssertEqual(InboxGuess.text(try item(#"{"id":"i","kind":"conflict","requiredInput":"choice","title":"t","extractorModel":"gpt-5.4-mini","extractorConfidence":0.85}"#)),
                       "gpt-5.4-mini's guess at 0.85")
        XCTAssertEqual(InboxGuess.text(try item(#"{"id":"i","kind":"conflict","requiredInput":"choice","title":"t","extractorConfidence":0.4}"#)),
                       "Cicada's guess at 0.40")
        XCTAssertNil(InboxGuess.text(try item(#"{"id":"i","kind":"conflict","requiredInput":"choice","title":"t","extractorModel":"m","informational":true}"#)))
    }

    func testTheHintsLinkIsItsFirstURL() {
        XCTAssertEqual(HintLink.firstURL(in: "You said https://example.com/alpha-project is where to check")?.host, "example.com")
        XCTAssertNil(HintLink.firstURL(in: "Only you know this"))
    }

    /// R-DI15 — every kind lands on a variant; free text keeps its two wire shapes.
    func testEveryKindHasAVariant() throws {
        let options = #","options":[{"key":"a","label":"A"},{"key":"b","label":"B"}]"#
        let table: [(String, FocusCardVariant)] = [
            (#"{"id":"1","kind":"conflict","requiredInput":"choice","title":"t"\#(options)}"#, .options),
            (#"{"id":"1","kind":"conflict","requiredInput":"choice","title":"t","informational":true\#(options)}"#, .informational),
            (#"{"id":"1","kind":"decay","requiredInput":"choice","title":"t"\#(options)}"#, .options),
            (#"{"id":"1","kind":"decay","requiredInput":"choice","title":"t"}"#, .legacyDecay),
            (#"{"id":"1","kind":"clarification","requiredInput":"freetext","title":"Who is bob-example?","allowOther":true,"allowDefer":true}"#, .freeText),
            (#"{"id":"1","kind":"merge_suggestion","requiredInput":"merge","title":"t"}"#, .merge),
            (#"{"id":"1","kind":"removal","requiredInput":"choice","title":"t","options":[{"key":"keep","label":"Keep"},{"key":"remove","label":"Remove"}]}"#, .options),
            (#"{"id":"1","kind":"divergence","requiredInput":"choice","title":"t"\#(options)}"#, .options),
            (#"{"id":"1","kind":"normalization","requiredInput":"choice","title":"t"\#(options)}"#, .options),
            (#"{"id":"1","kind":"followup","requiredInput":"choice","title":"t","question":"“Wire the lab cluster” — last heard 3 weeks ago. How did it go?","allowOther":true,"options":[{"key":"done","label":"Done"},{"key":"still","label":"Still going"},{"key":"stopped","label":"Stopped"},{"key":"didnt","label":"That didn't happen"},{"key":"remind_later","label":"Not now — ask again in 30 days"}]}"#, .options),
            (#"{"id":"1","kind":"conflict","requiredInput":"none","title":"t"}"#, .dismissOnly),
        ]
        for (json, expected) in table {
            XCTAssertEqual(FocusCardVariant.of(try item(json)), expected, json)
        }
        let legacy = try item(#"{"id":"1","kind":"clarification","requiredInput":"freetext","title":"t"}"#)
        XCTAssertEqual(FreeTextSubmit.resolution(for: legacy, text: "  a colleague "), QuestionResolution(action: "answer", answer: "a colleague"))
        let object = try item(#"{"id":"1","kind":"clarification","requiredInput":"freetext","title":"t","question":"Who?"}"#)
        XCTAssertEqual(FreeTextSubmit.resolution(for: object, text: "a colleague"), QuestionResolution(action: "resolve", answer: "a colleague"))
        XCTAssertNil(FreeTextSubmit.resolution(for: object, text: "   "))
    }
}
