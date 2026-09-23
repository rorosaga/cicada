import XCTest
@testable import CicadaApp

/// G136 plan R-SU1…R-SU4 — the one ranker. The palette's instant tier, the
/// graph typeahead (G123) and every in-page field rank and bold through
/// `QuickMatch`, so these pin the rules they share with each other and with
/// the server's `text_fold` (G136 R21).
final class QuickMatchTests: XCTestCase {
    private func tier(_ query: String, _ text: String) -> QuickMatch.Tier? {
        guard let token = QuickMatch.tokens(query).first else { return nil }
        return QuickMatch.hit(token, in: QuickMatch.fold(text))?.tier
    }

    private func score(_ query: String, _ text: String) -> Double? {
        QuickMatch.match(QuickMatch.tokens(query), fields: [QuickMatch.Field(text, weight: QuickMatch.Weight.name)])?.score
    }

    func testTiersRankWholeFieldThenPrefixThenWordStartThenInitialsThenSubstring() {
        XCTAssertEqual(tier("gamma", "Gamma"), .exact)
        XCTAssertEqual(tier("gam", "Gamma"), .prefix)
        XCTAssertEqual(tier("alp", "Beta alpha"), .wordStart)
        XCTAssertEqual(tier("cc", "Claude Code"), .initials)
        XCTAssertEqual(tier("alp", "Catalpha"), .substring)
        XCTAssertNil(tier("zeta", "Catalpha"))
        XCTAssertEqual([score("gamma", "Gamma"), score("gam", "Gamma"), score("alp", "Beta alpha"),
                        score("cc", "Claude Code"), score("alp", "Catalpha")], [5, 4, 3, 2, 1])
    }

    /// R-SU2: one letter lists what BEGINS with it, not everything that contains it.
    func testASingleCharacterMatchesOnlyAtAFieldOrWordStart() {
        XCTAssertEqual(tier("a", "Alpha"), .prefix)
        XCTAssertEqual(tier("a", "Beta alpha"), .wordStart)
        XCTAssertNil(tier("a", "Beta"), "no substring tier for one character")
        XCTAssertNil(tier("c", "Xc"), "no substring tier for one character")
    }

    func testEveryTokenMustMatchSomewhere() {
        let fields = [QuickMatch.Field("Alpha Project", weight: QuickMatch.Weight.name),
                      QuickMatch.Field("robotics", weight: QuickMatch.Weight.keyword)]
        XCTAssertNotNil(QuickMatch.match(QuickMatch.tokens("alpha robo"), fields: fields))
        XCTAssertNil(QuickMatch.match(QuickMatch.tokens("alpha zeta"), fields: fields), "AND, not OR")
        XCTAssertNil(QuickMatch.match([], fields: fields), "an empty query ranks nothing")
    }

    /// R-SU1: the server's fold, so the two tiers never disagree about one word.
    func testDiacriticsFoldButSharpSStaysAsTheServerIndexesIt() {
        XCTAssertEqual(tier("zurich", "Zürich"), .exact)
        XCTAssertEqual(tier("zürich", "Zurich"), .exact, "both sides fold")
        XCTAssertEqual(tier("zur", "Zu\u{0308}rich"), .prefix, "a decomposed input folds the same way")
        XCTAssertEqual(tier("straße", "Hauptstraße"), .substring)
        XCTAssertNil(tier("strasse", "Hauptstraße"), "G136 R21: no full case fold")
        XCTAssertEqual(tier("istanbul", "İstanbul"), .exact)
    }

    func testRangesAreOriginalScalarsSoADecomposedLetterIsBoldedWhole() {
        let decomposed = QuickMatch.match(QuickMatch.tokens("zur off"),
                                          fields: [QuickMatch.Field("Zu\u{0308}rich office", weight: 1)])
        XCTAssertEqual(decomposed?.ranges(inField: 0), [[0, 4], [8, 11]])
        let initials = QuickMatch.match(QuickMatch.tokens("cc"), fields: [QuickMatch.Field("Claude Code", weight: 1)])
        XCTAssertEqual(initials?.ranges(inField: 0), [[0, 1], [7, 8]])
        let overlap = QuickMatch.match(QuickMatch.tokens("alpha alp"), fields: [QuickMatch.Field("Alpha", weight: 1)])
        XCTAssertEqual(overlap?.ranges(inField: 0), [[0, 5]], "overlapping runs merge")
    }

    /// G136 R7 keeps the same surprise server-side, so the tiers agree.
    func testAnExactAliasOutranksANamePrefixBecauseWeightsMultiplyTiers() {
        let prefixOnName = QuickMatch.match(QuickMatch.tokens("delta"),
                                            fields: [QuickMatch.Field("Delta Ops", weight: QuickMatch.Weight.name)])?.score
        let exactAlias = QuickMatch.match(QuickMatch.tokens("delta"),
                                          fields: [QuickMatch.Field("Omega", weight: QuickMatch.Weight.name),
                                                   QuickMatch.Field("delta", weight: QuickMatch.Weight.alias)])?.score
        XCTAssertEqual(prefixOnName, 4.0)
        XCTAssertEqual(exactAlias ?? 0, 4.5, accuracy: 0.0001)
    }

    func testTokensAreWhitespaceSplitFoldedDedupedAndCappedAtEight() {
        XCTAssertEqual(QuickMatch.tokens("  Alpha  alpha ÄLPHA ").count, 1)
        XCTAssertEqual(QuickMatch.tokens((1...12).map { "w\($0)" }.joined(separator: " ")).count, QuickMatch.maxTokens)
        XCTAssertTrue(QuickMatch.tokens("   ").isEmpty)
    }

    func testWhitespaceRunsCollapseAndWordStartsSplitLikeUnicode61() {
        XCTAssertEqual(tier("alpha", "  alpha  "), .exact)
        XCTAssertEqual(QuickMatch.fold("a   b").scalars.count, 3)
        XCTAssertEqual(tier("vec", "sqlite-vec"), .wordStart)
        XCTAssertEqual(tier("vec", "sqlite_vec"), .wordStart, "unicode61 treats _ as a separator")
    }

    func testRankOrdersByScoreThenTieBreakThenName() {
        let items: [(String, String, Int)] = [("a", "Alpha Project", 3), ("b", "Alphabet", 7),
                                              ("c", "Beta alpha", 9), ("d", "Alphabet Inc", 7)]
        let ranked = QuickMatch.rank(items, query: "alpha",
                                     fields: { [QuickMatch.Field($0.1, weight: 1)] },
                                     tieBreak: { Double($0.2) }, name: { $0.1.lowercased() }).map { $0.item.0 }
        XCTAssertEqual(ranked, ["b", "d", "a", "c"])
    }

    func testMatchesKeepsEverythingForAnEmptyQuery() {
        XCTAssertTrue(QuickMatch.matches("", fields: []))
        XCTAssertTrue(QuickMatch.matches("gra", fields: [QuickMatch.Field("Graph physics", weight: 1)]))
        XCTAssertFalse(QuickMatch.matches("zeta", fields: [QuickMatch.Field("Graph physics", weight: 1)]))
    }
}
