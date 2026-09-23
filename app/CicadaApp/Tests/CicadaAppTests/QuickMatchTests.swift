import XCTest
@testable import CicadaApp

/// Design §1.2 — the one ranker. Pure: tiers, AND, diacritics, initials, weights.
final class QuickMatchTests: XCTestCase {
    func testTiersRankExactThenPrefixThenWordStartThenInitialsThenSubstring() {
        XCTAssertEqual(QuickMatch.tier(of: "sleep", in: "sleep")?.0, .exact)
        XCTAssertEqual(QuickMatch.tier(of: "sle", in: "sleep engine")?.0, .prefix)
        XCTAssertEqual(QuickMatch.tier(of: "eng", in: "sleep engine")?.0, .wordStart)
        XCTAssertEqual(QuickMatch.tier(of: "cc", in: "claude code")?.0, .initials)
        XCTAssertEqual(QuickMatch.tier(of: "gin", in: "sleep engine")?.0, .substring)
        XCTAssertNil(QuickMatch.tier(of: "zzz", in: "sleep engine"))
    }

    func testEveryTokenMustMatchSomeField() {
        let fields = [QuickMatch.Field("Text size", weight: QuickMatch.titleWeight),
                      QuickMatch.Field("zoom", weight: QuickMatch.keywordWeight)]
        XCTAssertNotNil(QuickMatch.match(QuickMatch.tokens("text zoom"), fields: fields))
        XCTAssertNil(QuickMatch.match(QuickMatch.tokens("text colour"), fields: fields), "AND, not OR")
    }

    func testDiacriticsAndCaseFold() {
        let fields = [QuickMatch.Field("Zürich", weight: QuickMatch.titleWeight)]
        XCTAssertNotNil(QuickMatch.match(QuickMatch.tokens("zurich"), fields: fields))
        XCTAssertNotNil(QuickMatch.match(QuickMatch.tokens("ZÜR"), fields: fields))
    }

    func testTitleOutweighsTheSameTierInAKeyword() {
        let inTitle = QuickMatch.match(["zoom"], fields: [QuickMatch.Field("Zoom", weight: QuickMatch.titleWeight)])!
        let inKeyword = QuickMatch.match(["zoom"], fields: [QuickMatch.Field("Text size", weight: QuickMatch.titleWeight),
                                                             QuickMatch.Field("zoom", weight: QuickMatch.keywordWeight)])!
        XCTAssertGreaterThan(inTitle.score, inKeyword.score)
    }

    func testTitleRangesAreCharacterOffsetsForBolding() {
        let m = QuickMatch.match(["size"], fields: [QuickMatch.Field("Text size", weight: QuickMatch.titleWeight)])!
        XCTAssertEqual(m.titleRanges, [5..<9])
    }
}
