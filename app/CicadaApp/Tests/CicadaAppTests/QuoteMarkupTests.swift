import XCTest
@testable import CicadaApp

/// R-DL2 / R-DL3 (DR-18, DR-56) — the words, without the markup they were written in, and every cited span still exact.
/// The owner's live check of #94 found `**bold**`, list dashes and `user:` / `assistant:` inside the Inbox's quote and
/// the Reader's turns.
final class QuoteMarkupTests: XCTestCase {
    private func strip(_ raw: String, lines: Bool = false) -> String {
        ExcerptText.stripMarkup(raw, keepLines: lines).text
    }

    func testEmphasisMarkersGoAndTheWordsStay() {
        XCTAssertEqual(strip("we use **sqlite-vec** now"), "we use sqlite-vec now")
        XCTAssertEqual(strip("it is *really* fast"), "it is really fast")
        XCTAssertEqual(strip("run `swift build` first"), "run swift build first")
        XCTAssertEqual(strip("keep `**as written**` in code"), "keep **as written** in code", "code is never re-read")
    }

    /// CommonMark flanking — what is not emphasis stays byte for byte.
    func testWhatIsNotEmphasisIsLeftAlone() {
        for raw in ["2**3 is eight", "call f(**kwargs, **options)", "a * b * c", "snake_case and __init__",
                    "**", "** spaced **", "the user: said so"] {
            XCTAssertEqual(strip(raw), raw, raw)
        }
    }

    func testRoleLabelsNeverShowInsideAQuote() {
        XCTAssertEqual(strip("user: moved it\nassistant: Noted."), "moved it\nNoted.")
        XCTAssertEqual(strip("speaker:Bob Example: we ship Friday"), "we ship Friday")
        XCTAssertEqual(strip("video [1:05]: the arm moves"), "the arm moves")
    }

    /// The labels are the writers' own (`evidence._TURN_RE`) — pinned to the one list the app keeps of them.
    func testEveryMarkerWordTheServerReadsIsStripped() {
        for word in EvidenceSpeaker.markerWords {
            XCTAssertEqual(strip("\(word): hi"), "hi", word)
            XCTAssertEqual(strip("\(word.uppercased()): hi"), "hi", word)
        }
    }

    func testLineMarkupInAQuoteAndInTheReader() {
        let raw = "# Plan\n- fast\n* local\n1. first\n> quoted"
        XCTAssertEqual(strip(raw), "Plan\nfast\nlocal\nfirst\nquoted")
        XCTAssertEqual(strip(raw, lines: true), "Plan\n• fast\n• local\n1. first\nquoted")
    }

    /// Deletion only: an offset maps by subtracting what was removed before it.
    func testOffsetsMapThroughEveryCut() {
        let s = ExcerptText.stripMarkup("user: the **new store** is fast", keepLines: false)
        XCTAssertEqual(s.text, "the new store is fast")
        XCTAssertEqual(s.map(12..<21), 4..<13, "the words")
        XCTAssertEqual(s.map(10..<23), 4..<13, "a span that took the markers too")
        XCTAssertEqual(s.map(0..<6), 0..<0, "a span that was only the label")
        XCTAssertEqual(s.map(31), 21, "the end")
    }

    func testQuotePartsKeepTheSpanWhenMarkersStraddleIt() {
        let p = ExcerptText.quoteParts(before: "the **new ", span: "store**", after: " is fast")
        XCTAssertEqual(p.before, "the new ")
        XCTAssertEqual(p.span, "store")
        XCTAssertEqual(p.after, " is fast")
    }

    /// The focus card's quote: labels and `**` gone, the wash on exactly the mention.
    func testTheFocusCardsQuoteSplitsAtTheMappedMention() throws {
        let json = #"{"id":"1","kind":"conflict","requiredInput":"choice","title":"t","cause":{"episodeId":"ep_1","excerpt":"user: we moved **alpha-project** to sqlite-vec\nassistant: Noted.","mentionOffsets":[[15,32]],"start":0,"tier":"claim","spanKind":"asserted"}}"#
        let item = try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
        XCTAssertEqual(QuoteSegments.of(item), [.init(text: "we moved ", mark: .plain),
                                                .init(text: "alpha-project", mark: .current),
                                                .init(text: " to sqlite-vec Noted.", mark: .plain)])
    }

    /// The Reader keeps the turn's lines; each wash is mapped through the cut.
    func testTheReaderMapsItsWashesThroughTheCut() {
        let block = ReaderBlock(index: 1, chunk: 0, role: "assistant", speaker: "Claude Code", mark: nil, time: nil,
                                text: "Use **sqlite-vec**:\n- fast\n- local", contentStart: 0,
                                washes: [ReaderWash(range: 4..<18, style: .focus), ReaderWash(range: 22..<26, style: .other)])
        XCTAssertEqual(ReaderText.segments(block), [
            .init(text: "Use ", mark: .plain), .init(text: "sqlite-vec", mark: .current),
            .init(text: ":\n• ", mark: .plain), .init(text: "fast", mark: .other),
            .init(text: "\n• local", mark: .plain)])
    }
}
