import XCTest
@testable import CicadaApp

/// Bugs 1 & 2 — a wikilink must render as a real link (not literal
/// `[[Entity Name]]` text) AND that link must actually be tappable
/// (`cicada://entity/<id>`, dispatched by `View.wikilinkNavigation`).
/// `MarkdownBody.linkifyWikilinks`/`sanitizeID` are the load-bearing pieces
/// of that rewrite — asserted directly here rather than only indirectly via
/// `AttributedString(markdown:)`, so a regression in the regex/sanitization
/// fails loudly instead of silently rendering plain text again.
final class MarkdownWikilinkTests: XCTestCase {

    // MARK: - `[[Entity Name]]`

    func test_plainWikilink_rewritesToMarkdownLink_withSanitizedID() {
        let out = MarkdownBody.linkifyWikilinks("See [[Stanford University]] for details.")
        XCTAssertEqual(out, "See [Stanford University](cicada://entity/stanford-university) for details.")
    }

    func test_multipleWikilinks_inOneString_bothRewrite() {
        let out = MarkdownBody.linkifyWikilinks("[[ETH Zurich]] and [[UCL]] both accepted him.")
        XCTAssertEqual(
            out,
            "[ETH Zurich](cicada://entity/eth-zurich) and [UCL](cicada://entity/ucl) both accepted him."
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
        XCTAssertEqual(linkRuns.first?.link, URL(string: "cicada://entity/camila-quintero"))
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
