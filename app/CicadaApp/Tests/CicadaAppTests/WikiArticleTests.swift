import XCTest
import SwiftUI
@testable import CicadaApp

/// The card's article (owner 2026-10-09): the page's prose as rows, read the way `MarkdownBody` always read it, with
/// the sections that have their own surface and the claims fence left out, each row knowing where it sits in the
/// served prose so a line can open its own source.
final class WikiArticleTests: XCTestCase {
    private func kinds(_ article: WikiArticle) -> [WikiRow.Kind] { article.rows.map(\.kind) }
    private func texts(_ article: WikiArticle) -> [String] { article.rows.map { String($0.text.characters) } }

    func testRowsFollowTheBlockGrammar() {
        let markdown = """
        ## Key Facts
        - First fact
          - A nested one
        1. Ordered

        A paragraph that
        wraps over two lines.

        > A quote
        > that continues
        ---
        ```swift
        let x = 1
        ```
        ### Small heading
        """
        let article = WikiArticle.build(markdown)
        XCTAssertEqual(kinds(article), [
            .heading(level: 2), .item(marker: "•", indent: 0), .item(marker: "•", indent: 1), .item(marker: "1.", indent: 0),
            .paragraph, .quote, .rule, .code, .heading(level: 3),
        ])
        XCTAssertEqual(texts(article), ["Key Facts", "First fact", "A nested one", "Ordered",
                                        "A paragraph that wraps over two lines.", "A quote that continues", "",
                                        "let x = 1", "Small heading"])
        XCTAssertTrue(article.complete)
    }

    func testTheSectionsWithTheirOwnSurfaceAndTheClaimsFenceAreLeftOut() {
        let markdown = """
        ## Summary
        The header shows this.
        ### Still the summary's
        ## Key Facts
        - Kept
        ```claims
        {"id":"clm_1","text":"machine data"}
        ```
        ## Description
        A media card shows this.
        ## Notes
        Kept too.
        """
        XCTAssertEqual(texts(WikiArticle.build(markdown)), ["Key Facts", "Kept", "Notes", "Kept too."])
        // An unterminated fence hides everything after it (R-FX8): machine YAML is never prose.
        XCTAssertEqual(texts(WikiArticle.build("## Key Facts\n- Kept\n```claims\n- id: a\n## Later\nhidden")),
                       ["Key Facts", "Kept"])
    }

    func testASummaryOnlyPageHasNoArticleAndItsBeliefsAreItsContent() {
        XCTAssertTrue(WikiArticle.build("## Summary\nOnly this.\n").isEmpty)
        XCTAssertTrue(WikiArticle.build("").isEmpty)
        XCTAssertFalse(WikiArticle.build("## Summary\nOnly this.\n\n## Key Facts\n- One").isEmpty)
    }

    func testEmbedsAndImagesBecomeRowsOfTheirOwn() {
        let article = WikiArticle.build("Before ![[alpha-project]] after\n\n- ![logo](https://example.com/a.png)")
        XCTAssertEqual(kinds(article), [.paragraph, .embed(ref: "alpha-project"), .paragraph,
                                        .image(url: "https://example.com/a.png", alt: "logo")])
    }

    func testWikilinksAreEntityLinksAndPlainRunsTakeTheTextsColour() {
        let text = WikiArticle.build("- Works with [[Bob Example]] and **ships**").rows[0].text
        let link = text.runs.first { $0.link != nil }
        XCTAssertEqual(link?.link, URL(string: "cicada://entity/Bob%20Example"))
        XCTAssertEqual(link?.underlineStyle, .single)
        XCTAssertTrue(text.runs.filter { $0.link == nil }.allSatisfy { $0.foregroundColor == nil },
                      "a cached article must follow a theme change")
    }

    /// Offsets are Unicode scalars — Python's `str` offsets, which `/provenance`'s `bodyRanges` use.
    func testARowKnowsWhereItSitsInTheServedProse() {
        let body = "## Key Facts\n- Café crème déjà vu 🎉 first fact.\n- Second fact here."
        let rows = WikiArticle.build(body).rows
        XCTAssertEqual(rows[2].source, 48..<67, "python: body.index('- Second') == 48")
        let scalars = Array(body.unicodeScalars)
        for row in rows {
            let line = String(String.UnicodeScalarView(scalars[row.source]))
            XCTAssertTrue(line.contains(String(row.text.characters)), line)
        }
    }

    func testAFirstScreenIsExactlyTheArticlesStart() {
        let full = WikiArticle.build(WikiPageFixture.prose)
        for cap in [1, 5, 48, 300] {
            let head = WikiArticle.build(WikiPageFixture.prose, maxRows: cap)
            XCTAssertEqual(head.rows, Array(full.rows.prefix(cap)))
            XCTAssertFalse(head.complete)
        }
        XCTAssertTrue(WikiArticle.build("## Key Facts\n- One", maxRows: 48).complete)
    }

    @MainActor
    func testTheCacheDrawsTheFirstScreenThenTheWholeArticleAndKeepsAFew() async {
        let cache = WikiArticleCache(capacity: 2)
        let key = WikiArticleCache.Key(markdown: WikiPageFixture.prose, dropping: WikiArticle.ownSurfaces)
        XCTAssertEqual(cache.article(key).rows.count, WikiArticleCache.firstScreenRows)
        await cache.build(key)
        XCTAssertTrue(cache.article(key).complete)
        XCTAssertGreaterThan(cache.article(key).rows.count, 1_500)
        for n in 0..<3 {
            let other = WikiArticleCache.Key(markdown: WikiPageFixture.prose + "\n\nExtra \(n).", dropping: [])
            await cache.build(other)
        }
        XCTAssertNil(cache.built[key], "the oldest article is let go")
        XCTAssertEqual(cache.built.count, 2)
    }

    // MARK: - A line's provenance

    private func provenance(hash: String, ranges: [[Int]]) throws -> EntityProvenance {
        let json = """
        {"entityId":"owner-example","conversations":[],"totals":{"claims":0},"pageBodyHash":"\(hash)",
         "sections":[{"key":"key-facts","title":"Key Facts","items":[{"identity":"i1","text":"Second fact here.",
           "bodyRanges":\(ranges),"evidence":[{"sourceTitle":"Conversation A","sourceAvailable":true,"status":"exact",
             "span":{"episode":"ep_2026-01-02_001","start":10,"end":30,"hash":"abc","kind":"user","excerpt":"x",
                     "excerptStart":0}}]}]}]}
        """
        return try JSONDecoder().decode(EntityProvenance.self, from: Data(json.utf8))
    }

    func testALineOpensTheSourceOfTheItemThatCoversIt() throws {
        let body = "## Key Facts\n- Café crème déjà vu 🎉 first fact.\n- Second fact here."
        XCTAssertEqual(LineProvenance.bodyHash(body), "a0bc62ef4db6", "python: sha256(body)[:12]")
        let rows = WikiArticle.build(body).rows
        let p = try provenance(hash: "a0bc62ef4db6", ranges: [[50, 67]])
        let target = LineProvenance.target(for: rows[2], body: body, provenance: p, subjectId: "owner-example")
        XCTAssertEqual(target?.episode, "ep_2026-01-02_001")
        XCTAssertEqual(target?.focus, .span(start: 10, end: 30, hash: "abc", derived: false))
        XCTAssertEqual(target?.knownTitle, "Conversation A")
        XCTAssertNil(LineProvenance.target(for: rows[1], body: body, provenance: p, subjectId: "owner-example"),
                     "no item covers the first fact")
        // The page changed since `/provenance` was read: its ranges describe other text, so no line trusts them.
        XCTAssertNil(LineProvenance.target(for: rows[2], body: body + " edited", provenance: p, subjectId: "owner-example"))
        XCTAssertNil(LineProvenance.target(for: rows[2], body: body, provenance: nil, subjectId: "owner-example"))
    }
}
