import XCTest
@testable import CicadaApp

/// G233, ruling 48 (DR-38): a book page leads with the book. Its description is the article's, never the header's;
/// no globe box, no "no relation" line, no empty cover slot.
final class BookPageLayoutTests: XCTestCase {
    private let page = "## Summary\nA lamplighter learns the orchard keeps its hours.\n\nFrom [Open Library](https://example.org/w), saved 5 Nov"

    private var book: MediaBlock { MediaBlock(url: "https://example.org/w", mediaType: "url", kind: "book") }
    private var link: MediaBlock { MediaBlock(url: "https://example.org/a", mediaType: "url") }

    func testTheHeaderHoldsNoSummaryForABookButDoesForAnyOtherPage() {
        XCTAssertNil(EntityHeaderWords.summary(markdown: page, isStub: false, isBook: true))
        XCTAssertNotNil(EntityHeaderWords.summary(markdown: page, isStub: false))
    }

    func testABooksArticleKeepsTheDescriptionAndItsSourceLineWithoutTheHeading() {
        let article = EntityHeaderWords.articleMarkdown(page, isBook: true)
        XCTAssertFalse(article.contains("## Summary"))
        XCTAssertTrue(article.hasPrefix("A lamplighter learns"))
        XCTAssertTrue(article.contains("From [Open Library]"))
        XCTAssertEqual(EntityHeaderWords.articleMarkdown(page, isBook: false), page)
    }

    func testNoRelationLineOnABookButARealRelationStillShows() {
        let none = EntityRelevance(tense: "none", line: "No personal relation on the record")
        let some = EntityRelevance(tense: "past", line: "Read it last spring", conversations: 2)
        XCTAssertFalse(PageInShort.isDrawn(relevance: none, media: book))
        XCTAssertFalse(PageInShort.isDrawn(relevance: nil, media: book))
        XCTAssertTrue(PageInShort.isDrawn(relevance: some, media: book))
        XCTAssertTrue(PageInShort.isDrawn(relevance: none, media: link))
    }

    func testABookDrawsNoPreviewBox() {
        var entity = Entity(id: "lantern-orchard", name: "The Lantern Orchard", type: .media, status: .active,
                            confidence: 0.9, created: "2026-01-05", lastReferenced: "2026-08-25", decayRate: 0.05,
                            sourceEpisodes: [], tags: [], related: [], version: 1, markdownContent: page, history: [])
        entity.media = book
        XCTAssertFalse(HeroPreview.hasPreviewableAsset(for: entity))
    }
}
