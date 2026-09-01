import XCTest
@testable import CicadaApp

/// Bugs 1 & 2 — a wikilink must render as a real link (not literal
/// `[[Entity Name]]` text) AND that link must actually be tappable
/// (`cicada://entity/<ref>`, dispatched by `View.wikilinkNavigation`).
/// `MarkdownBody.linkifyWikilinks`/`entityLink`/`resolveEntityID` are the
/// load-bearing pieces of that rewrite — asserted directly here rather than
/// only indirectly via `AttributedString(markdown:)`, so a regression in the
/// regex/encoding/resolution fails loudly instead of silently rendering
/// plain text (or a dead link to a nonexistent id) again.
final class MarkdownWikilinkTests: XCTestCase {

    // MARK: - `[[Entity Name]]`

    /// The URL carries the display name VERBATIM (percent-encoded), never a
    /// pre-sanitized id — resolution to a real id happens at click time
    /// against the graph (see `resolveEntityID` below). PR #29 round 2.
    func test_plainWikilink_rewritesToMarkdownLink_carryingTheDisplayName() {
        let out = MarkdownBody.linkifyWikilinks("See [[Stanford University]] for details.")
        XCTAssertEqual(out, "See [Stanford University](cicada://entity/Stanford%20University) for details.")
    }

    func test_multipleWikilinks_inOneString_bothRewrite() {
        let out = MarkdownBody.linkifyWikilinks("[[ETH Zurich]] and [[UCL]] both accepted him.")
        XCTAssertEqual(
            out,
            "[ETH Zurich](cicada://entity/ETH%20Zurich) and [UCL](cicada://entity/UCL) both accepted him."
        )
    }

    func test_punctuatedWikilink_isNotSanitizedAtMintTime() {
        // `&` and `'` survive (encoded) so the click-time resolver can match
        // the node's real name; `sanitizeID` would have thrown them away here
        // and minted a link to a stem that doesn't exist.
        let out = MarkdownBody.linkifyWikilinks("[[Algorithms & Data Structures]]")
        XCTAssertEqual(
            out,
            "[Algorithms & Data Structures](cicada://entity/Algorithms%20%26%20Data%20Structures)"
        )
    }

    func test_textWithoutWikilinks_isUnchanged() {
        let plain = "Just a plain sentence with no brackets at all."
        XCTAssertEqual(MarkdownBody.linkifyWikilinks(plain), plain)
    }

    // MARK: - `[[id|Alias]]`

    func test_aliasedWikilink_displaysAlias_linksToID() {
        let out = MarkdownBody.linkifyWikilinks("Reports to [[camila-quintero|Camila]].")
        XCTAssertEqual(out, "Reports to [Camila](cicada://entity/camila-quintero).")
    }

    func test_aliasedWikilink_trimsWhitespaceAroundBothHalves() {
        let out = MarkdownBody.linkifyWikilinks("[[ camila-quintero | Camila Quintero ]]")
        XCTAssertEqual(out, "[Camila Quintero](cicada://entity/camila-quintero)")
    }

    // MARK: - URL mint/parse round-trip

    func test_entityLink_roundTripsEveryRefThroughTheURL() {
        // Names the naive `lastPathComponent`-of-a-raw-string approach would
        // mangle: a slash (path separator), a percent sign, non-ASCII,
        // and the `&`/`'` punctuation the resolver needs intact.
        for ref in ["Cicada / Thesis", "50% off", "Atlético de Madrid", "O'Brien & Co.", "camila-quintero"] {
            let url = try? XCTUnwrap(URL(string: MarkdownBody.entityLink(for: ref)), ref)
            XCTAssertEqual(url.flatMap(MarkdownBody.wikilinkRef(from:)), ref)
        }
    }

    func test_wikilinkRef_rejectsNonCicadaURLs() {
        XCTAssertNil(MarkdownBody.wikilinkRef(from: URL(string: "https://example.com/entity/x")!))
        XCTAssertNil(MarkdownBody.wikilinkRef(from: URL(string: "cicada://entity/")!))
    }

    // MARK: - Click-time resolution against the graph snapshot

    private let nodes = [
        GraphNode(id: "algorithms-&-data-structures", name: "Algorithms & Data Structures", type: .concept),
        GraphNode(id: "o'brien-&-co", name: "O'Brien & Co.", type: .company),
        GraphNode(id: "camila-quintero", name: "Camila Quintero", type: .person),
    ]

    func test_resolveEntityID_exactIDMatch_wins() {
        XCTAssertEqual(MarkdownBody.resolveEntityID("camila-quintero", in: nodes), "camila-quintero")
        XCTAssertEqual(MarkdownBody.resolveEntityID("o'brien-&-co", in: nodes), "o'brien-&-co")
    }

    func test_resolveEntityID_punctuatedName_resolvesToTheNodesRealID() {
        // The reviewer's case: the real filename keeps the `&`, so the
        // sanitized form (`algorithms-data-structures`) would 404.
        XCTAssertEqual(
            MarkdownBody.resolveEntityID("Algorithms & Data Structures", in: nodes),
            "algorithms-&-data-structures"
        )
        XCTAssertEqual(MarkdownBody.resolveEntityID("O'Brien & Co.", in: nodes), "o'brien-&-co")
    }

    func test_resolveEntityID_nameMatch_isCaseInsensitive() {
        XCTAssertEqual(
            MarkdownBody.resolveEntityID("algorithms & data structures", in: nodes),
            "algorithms-&-data-structures"
        )
        XCTAssertEqual(MarkdownBody.resolveEntityID("CAMILA QUINTERO", in: nodes), "camila-quintero")
    }

    func test_resolveEntityID_unknownName_fallsBackToTheSanitizedForm() {
        XCTAssertEqual(MarkdownBody.resolveEntityID("Stanford University", in: nodes), "stanford-university")
        XCTAssertEqual(MarkdownBody.resolveEntityID("O'Brien & Co.", in: []), "o-brien-co")
    }

    func test_renderWikilinks_claimText_mintsTheSameURLAsTheBodyRenderer() {
        // ClaimChip must go through the same mint path as MarkdownBody so a
        // claim's wikilink and a body's wikilink for one name can't drift.
        let claim = renderWikilinks("works at [[Algorithms & Data Structures]]")
        let body = MarkdownBody.inlineAttributed("works at [[Algorithms & Data Structures]]")
        let claimLink = claim.runs.compactMap(\.link).first
        let bodyLink = body.runs.compactMap(\.link).first
        XCTAssertNotNil(claimLink)
        XCTAssertEqual(claimLink, bodyLink)
        XCTAssertEqual(claimLink.flatMap(MarkdownBody.wikilinkRef(from:)), "Algorithms & Data Structures")
    }

    // MARK: - ID sanitization

    func test_sanitizeID_lowercasesAndDashesSpaces() {
        XCTAssertEqual(MarkdownBody.sanitizeID("Stanford University"), "stanford-university")
    }

    func test_sanitizeID_collapsesRunsOfPunctuationToASingleDash() {
        // Apostrophe, "&", and trailing "." are all non-alphanumeric — none
        // of them should survive as literal characters, and the "&"
        // surrounded by spaces must collapse to ONE dash, not three.
        XCTAssertEqual(MarkdownBody.sanitizeID("O'Brien & Co."), "o-brien-co")
    }

    func test_sanitizeID_trimsLeadingAndTrailingDashes() {
        XCTAssertEqual(MarkdownBody.sanitizeID("  --Weird Name--  "), "weird-name")
    }

    func test_sanitizeID_alreadyDashedID_isIdempotent() {
        XCTAssertEqual(MarkdownBody.sanitizeID("camila-quintero"), "camila-quintero")
    }

    // MARK: - End-to-end: the AttributedString a `Text` actually renders

    func test_inlineAttributed_wikilink_carriesTheCicadaEntityLink() {
        let attr = MarkdownBody.inlineAttributed("Studied under [[Camila Quintero]].")
        let linkRuns = attr.runs.filter { $0.link != nil }
        XCTAssertEqual(linkRuns.count, 1, "the wikilink span must produce exactly one linked run")
        XCTAssertEqual(linkRuns.first?.link, URL(string: "cicada://entity/Camila%20Quintero"))
    }

    func test_inlineAttributed_aliasedWikilink_showsAliasAsTheVisibleText() {
        let attr = MarkdownBody.inlineAttributed("[[camila-quintero|Camila]]")
        XCTAssertEqual(String(attr.characters), "Camila")
        let linkRuns = attr.runs.filter { $0.link != nil }
        XCTAssertEqual(linkRuns.first?.link, URL(string: "cicada://entity/camila-quintero"))
    }

    func test_inlineAttributed_plainText_carriesNoLink() {
        let attr = MarkdownBody.inlineAttributed("No wikilinks here at all.")
        XCTAssertTrue(attr.runs.allSatisfy { $0.link == nil })
    }
}
