import XCTest
@testable import CicadaApp

/// The card's evidence (owner 2026-11-24): a conversation as the Reader's own chat rows over the turns the server cut
/// around the mention, a note as whole sentences, a name found by searching washed and not underlined, a cut said with
/// "…", and a question stored before any of it still drawn. Every conversation is synthetic.
final class QuestionEvidenceTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!

    private func item(_ cause: String, extra: String = "") throws -> InboxItem {
        let json = #"{"id":"inbox-001","kind":"merge_suggestion","requiredInput":"merge","title":"t"\#(extra),"cause":\#(cause)}"#
        return try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    /// Three turns as `evidence_window.chat` serves them: "Then do you think …" / "I am not sure. Is Sam Example …" / "No idea."
    private let chatCause = #"""
    {"episodeId":"ep_2026-08-20_002","timestamp":"2026-08-20T10:00:00+00:00","harness":"claude-code","origin":"claude-code",
     "conversationTitle":"Lab trip","tier":"item","spanKind":"derived",
     "excerpt":"Then do you think Samuel Example could join?\nI am not sure. Is Sam Example the same person as Samuel Example?\nNo idea.",
     "mentionOffsets":[[63,74],[18,32],[94,108]],"focus":[120,131],
     "turns":[{"index":1,"start":0,"contentStart":0,"end":44,"role":"user","marker":"user","cutBefore":true},
              {"index":2,"start":45,"contentStart":45,"end":109,"role":"assistant","marker":"assistant"},
              {"index":3,"start":110,"contentStart":110,"end":118,"role":"user","marker":"user","cutAfter":true}]}
    """#

    func testAConversationIsTheReadersRowsWithEachTurnOnItsOwnSide() throws {
        let chat = try XCTUnwrap(QuestionEvidence.chat(try XCTUnwrap(item(chatCause).cause), timeZone: utc))
        let messages = chat.rows.compactMap { row -> ReaderChat.Message? in
            if case let .message(m) = row.kind { return m } else { return nil }
        }
        XCTAssertEqual(messages.map(\.side), [.person, .other, .person], "who spoke is the side, never a paragraph")
        XCTAssertFalse(chat.rows.contains { if case .day = $0.kind { true } else { false } }, "the source line names the day")
        XCTAssertEqual(chat.rows.first?.gap, ReaderChat.Gap.none)
        XCTAssertEqual(chat.focusTurn, 2, "the turn holding the mention reads primary")
    }

    func testTheMentionAndTheOtherSidesNamesAreWashedAndNeverUnderlined() throws {
        let chat = try XCTUnwrap(QuestionEvidence.chat(try XCTUnwrap(item(chatCause).cause), timeZone: utc))
        let washes = chat.rows.compactMap { row -> [ReaderWash]? in
            if case let .message(m) = row.kind { return m.block.washes } else { return nil }
        }.flatMap { $0 }
        XCTAssertFalse(washes.isEmpty)
        XCTAssertTrue(washes.allSatisfy { $0.style == .found }, "found by searching: washed, semibold, no underline")
    }

    func testAnAssertedSpanKeepsItsUnderlineAndTheNamesBesideItAreFound() throws {
        let asserted = chatCause.replacingOccurrences(of: #""spanKind":"derived""#, with: #""spanKind":"asserted""#)
        let chat = try XCTUnwrap(QuestionEvidence.chat(try XCTUnwrap(item(asserted).cause), timeZone: utc))
        let styles = chat.rows.compactMap { row -> [ReaderWash]? in
            if case let .message(m) = row.kind { return m.block.washes } else { return nil }
        }.flatMap { $0 }.map(\.style)
        XCTAssertTrue(styles.contains(.focus))
        XCTAssertTrue(styles.contains(.found))
    }

    func testACutTurnReadsWithAnEllipsisAndItsWashesMoveWithTheWords() throws {
        let blocks = QuestionEvidence.edged(
            [ReaderBlock(index: 1, chunk: 0, role: "user", speaker: "You", mark: nil, time: nil, text: "Is Sam here", contentStart: 0,
                         washes: [ReaderWash(range: 3..<6, style: .found)])],
            cuts: [1: (true, true)])
        XCTAssertEqual(blocks[0].text, "… Is Sam here …")
        XCTAssertEqual(blocks[0].washes[0].range, 5..<8)
        XCTAssertEqual(ScalarText(blocks[0].text).slice(5, 8), "Sam")
    }

    func testAStoredQuestionWithNoTurnsStillDrawsAsAQuote() throws {
        let old = try item(#"{"episodeId":"ep_1","excerpt":"Discussed swapping the store","mentionOffsets":[[10,18]],"start":0,"tier":"claim","spanKind":"derived"}"#)
        XCTAssertEqual(old.cause?.turns, [])
        XCTAssertNil(old.cause?.focus)
        guard case let .quote(segments) = QuestionEvidence.of(old) else { return XCTFail("a quote") }
        XCTAssertEqual(segments.map(\.mark), [.plain, .found, .plain])
        XCTAssertEqual(QuestionEvidence.of(try item(#"{"excerpt":"[ no source recorded ]","tier":"none"}"#)), .none)
    }

    func testAQuoteInWholeSentencesSaysWhereItWasCutAndMarksEveryMention() throws {
        let note = try item(#"{"episodeId":"ep_1","excerpt":"Sam Example gave the talk. Samuel Example asked.","mentionOffsets":[[0,11],[27,41]],"start":100,"tier":"claim","spanKind":"asserted","cutBefore":true,"cutAfter":true}"#)
        guard case let .quote(segments) = QuestionEvidence.of(note) else { return XCTFail("a quote") }
        XCTAssertEqual(segments.first, .init(text: QuoteCut.before, mark: .plain))
        XCTAssertEqual(segments.last, .init(text: QuoteCut.after, mark: .plain))
        XCTAssertEqual(segments.filter { $0.mark == .current }.map(\.text), ["Sam Example"], "only the quoted span is underlined")
        XCTAssertEqual(segments.filter { $0.mark == .found }.map(\.text), ["Samuel Example"])
    }

    func testShowInConversationLandsOnTheServersFocusWhenTheExcerptHasNoOrigin() throws {
        let cause = try XCTUnwrap(item(chatCause).cause)
        XCTAssertNil(cause.start)
        guard case let .span(start, end, _, derived)? = cause.readerTarget(subjectId: nil)?.focus else { return XCTFail("a span") }
        XCTAssertEqual([start, end], [120, 131])
        XCTAssertTrue(derived)
        let plain = try XCTUnwrap(item(#"{"episodeId":"ep_1","excerpt":"x Sam y","mentionOffsets":[[2,5]],"start":40,"tier":"item"}"#).cause)
        guard case let .span(s, e, _, _)? = plain.readerTarget(subjectId: nil)?.focus else { return XCTFail("a span") }
        XCTAssertEqual([s, e], [42, 45], "a plain excerpt still sits at start + offset")
    }

    func testASummaryTheGraphClippedEndsAtAWholeWord() {
        let clipped = String(("Sam Example is a researcher in the lab who works on retrieval and memory systems for agents, and who also " +
            "maintains the shared evaluation harness the whole group uses every week, including the nightly regression runs").prefix(200))
        XCTAssertEqual(clipped.count, 200)
        let shown = MergePair.wholeWords(clipped)
        XCTAssertEqual(shown?.hasSuffix("…"), true)
        XCTAssertFalse(shown?.contains("regress") == true && shown?.hasSuffix("regress…") == true, "never mid-word")
        XCTAssertEqual(MergePair.wholeWords("A short summary."), "A short summary.")
        XCTAssertNil(MergePair.wholeWords("  "))
        XCTAssertNil(MergePair.wholeWords(nil))
    }
}
