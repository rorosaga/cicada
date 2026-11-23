import XCTest
import SwiftUI
@testable import CicadaApp

/// Owner 2026-11-23 (DESIGN_RULES §9, "a link never shows as brackets"): page text shown as a plain line reads as the
/// page's own name, never as `[[…]]`, a bare id or a raw `**`. Pure rules here; the look is in the PR's screenshots.
final class PageLineTests: XCTestCase {
    private let nodes = [
        GraphNode(id: "bob-example", name: "Bob Example", type: .person, aliases: ["Bobby E."]),
        GraphNode(id: "alpha-project", name: "Alpha Project", type: .project),
        GraphNode(id: "gamma-ide", name: "Gamma", type: .concept, displayName: "Gamma (IDE)"),
        GraphNode(id: "gamma-program", name: "Gamma", type: .concept, displayName: "Gamma (program)"),
    ]
    private var index: PageLinkIndex { PageLinkIndex(nodes: nodes) }

    private func plain(_ raw: String, excerpt: Bool = false) -> String {
        PageLine.plain(raw, links: index, excerpt: excerpt)
    }

    // MARK: A link reads as the page's own name

    func testEveryWrittenSpellingOfAPageReadsAsItsName() {
        for written in ["[[bob-example]]", "[[bob-example|Bob]]", "[[Bobby E.]]", "[[bob example]]", "![[bob-example]]"] {
            XCTAssertEqual(plain("Met \(written) today."), "Met Bob Example today.", written)
        }
    }

    func testAnUnknownOrAmbiguousLinkReadsAsItsWrittenWordsWithoutBrackets() {
        XCTAssertEqual(plain("See [[Gamma]] now."), "See Gamma now.", "two pages answer to it")
        XCTAssertEqual(plain("See [[Nobody Known]] now."), "See Nobody Known now.")
        XCTAssertEqual(plain("See [[nobody-known|that person]] now."), "See that person now.", "the written display words")
        XCTAssertEqual(plain("See [[nobody-known]] now."), "See Nobody Known now.", "a slug is never a bare id")
    }

    func testNothingLeftHoldsABracketPair() {
        let raw = "A [[bob-example]] and [[ghost-page|Ghost]], plus ![[alpha-project]] and [[gamma]]."
        XCTAssertFalse(PageLine.hasBrackets(plain(raw)))
    }

    // MARK: A snippet can cut a link in half

    func testAHalfLinkAtASnippetsEdgeReadsAsWords() {
        XCTAssertEqual(plain("…the favourite of [[Rodri"), "…the favourite of Rodri")
        XCTAssertEqual(plain("…the favourite of [[Rodri…"), "…the favourite of Rodri…")
        XCTAssertEqual(plain("…the favourite of [[rodrigo-sag|Rod"), "…the favourite of Rod")
        XCTAssertEqual(plain("odrigo Sagastegui]] said so"), "odrigo Sagastegui said so")
        XCTAssertEqual(plain("…ia-barros|Julia]] said so"), "Julia said so")
        XCTAssertFalse(PageLine.hasBrackets(plain("tail [[a")))
    }

    func testCodeWithBracketsIsLeftAlone() {
        XCTAssertEqual(plain("use a[b[0]] here"), "use a[b[0]] here")
        XCTAssertEqual(plain("call arr[0](x) now"), "call arr[0](x) now")
    }

    func testAnIndexExpressionIsCodeNotALink() {
        XCTAssertEqual(plain(#"use df[["a", "b"]] and grid[[0, 1]] here"#), #"use df[["a", "b"]] and grid[[0, 1]] here"#)
    }

    // MARK: The Reader and a quote keep their words and lose the brackets (deletion only)

    func testTheReaderStripsABracketedLinkByDeletionAlone() {
        let raw = "see [[bob-example|Bob]] and [[Alpha Project]] and ![[alpha-project]]"
        let stripped = ExcerptText.stripMarkup(raw, keepLines: true)
        XCTAssertEqual(stripped.text, "see Bob and Alpha Project and alpha-project")
        // "Alpha Project" sat at 30..43 of the raw text and is still those words, found by the offset map.
        let range = stripped.map(30..<43)
        XCTAssertEqual(ScalarText(stripped.text).slice(range.lowerBound, range.upperBound), "Alpha Project")
        XCTAssertEqual(ExcerptText.stripMarkup(#"df[["a"]] and x[[0]]"#, keepLines: true).text, #"df[["a"]] and x[[0]]"#)
        XCTAssertEqual(ExcerptText.stripMarkup("…of [[Rodri", keepLines: true).text, "…of Rodri")
        XCTAssertEqual(ExcerptText.stripMarkup("odrigo]] said", keepLines: true).text, "odrigo said")
    }

    // MARK: Markup

    func testEmphasisAndCodeMarkersGoAndSnakeCaseStays() {
        XCTAssertEqual(plain("**Bold** and *soft* and `code` and _under_ and __strong__"),
                       "Bold and soft and code and under and strong")
        XCTAssertEqual(plain("keeps snake_case, 2**3 and a * b"), "keeps snake_case, 2**3 and a * b")
        XCTAssertEqual(plain("**[[bob-example]]** works at [[alpha-project]]"), "Bob Example works at Alpha Project")
    }

    func testAMarkdownLinkReadsAsItsText() {
        XCTAssertEqual(plain("Read [the paper](https://example.com/p) first"), "Read the paper first")
    }

    func testAPagesOwnSentenceKeepsItsLineStartButASnippetLosesATurnLabel() {
        XCTAssertEqual(plain("System: Linux is fine"), "System: Linux is fine")
        XCTAssertEqual(plain("- a minus"), "- a minus")
        XCTAssertEqual(plain("user: hello there", excerpt: true), "hello there")
    }

    func testNewlinesReadAsSpaces() {
        XCTAssertEqual(plain("one\ntwo [[bob-example]]\nthree"), "one two Bob Example three")
    }

    func testPlainTextIsReturnedUntouched() {
        let c = PageLine.cleaned("nothing to do here", links: index)
        XCTAssertEqual(c.text, "nothing to do here")
        XCTAssertEqual(c.map(2..<9), 2..<9)
    }

    // MARK: Highlighting follows the cut

    private func bold(_ raw: String, _ offsets: [[Int]], excerpt: Bool = true) -> [String] {
        let out = PageLine.attributed(raw, bold: offsets, links: index, excerpt: excerpt)
        return out.runs.compactMap { run in
            out[run.range].inlinePresentationIntent == .stronglyEmphasized ? String(out[run.range].characters) : nil
        }
    }

    func testAHighlightOnPlainWordsStaysOnThem() {
        // "Alpha" at 5..10 of "Work Alpha rocks"
        XCTAssertEqual(bold("Work Alpha rocks", [[5, 10]]), ["Alpha"])
    }

    func testAHighlightAfterALinkMovesWithTheName() {
        let raw = "[[bob-example]] likes tea" // "tea" 22..25
        XCTAssertEqual(PageLine.plain(raw, links: index), "Bob Example likes tea")
        XCTAssertEqual(bold(raw, [[22, 25]]), ["tea"])
    }

    func testAHighlightInsideALinkMarksTheWholeName() {
        let raw = "We met [[bob-example]] there" // "bob" inside the ref: 9..12
        XCTAssertEqual(bold(raw, [[9, 12]]), ["Bob Example"])
    }

    func testAHighlightAcrossMarkersMarksTheWords() {
        let raw = "a **strong word** here" // "strong word" 4..15
        XCTAssertEqual(bold(raw, [[4, 15]]), ["strong word"])
    }

    func testAStaleHighlightIsIgnored() {
        XCTAssertEqual(bold("short", [[3, 99], [-1, 2], [2, 2]]), [])
    }

    // MARK: Lists stay fast

    func testAFourThousandLineListIsNotAPerRowScanOfEveryPage() {
        let many = (0..<4_000).map { GraphNode(id: "page-\($0)", name: "Page \($0)", type: .concept) }
        let big = PageLinkIndex(nodes: many)
        let start = Date()
        for n in 0..<4_000 {
            _ = PageLine.plain("**x** [[page-\(n)]] and [[Page \((n + 1) % 4_000)]] with `code`", links: big)
        }
        XCTAssertLessThan(Date().timeIntervalSince(start), 2.0)
    }

    // MARK: The first line

    func testFirstLineIsResolvedBeforeItIsCut() {
        XCTAssertEqual(PageLine.firstLine("\n\n**Lead** about [[alpha-project]].\nSecond.", links: index),
                       "Lead about Alpha Project.")
        XCTAssertNil(PageLine.firstLine("  \n ", links: index))
    }
}
