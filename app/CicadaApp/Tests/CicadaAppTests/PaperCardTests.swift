import XCTest
@testable import CicadaApp

/// G133 / G121 — the paper card's sentences, the Feed row's byline and search,
/// and the wire shapes they decode from (R7 §5.2).
final class PaperCardTests: XCTestCase {
    private func item(_ extra: String = "") throws -> MediaFeedItem {
        let json = """
        {"mediaEntityId": "media-arxiv-2401-00001", "url": "https://arxiv.org/abs/2401.00001",
         "title": "Paper Alpha", "mediaType": "url", "savedAt": "2026-09-01T00:00:00+00:00" \(extra)}
        """
        return try JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
    }

    func testBylines() {
        XCTAssertEqual(PaperCardText.byline(authors: ["Ada Example", "Bob Example"], venue: "Journal of Examples",
                                            published: "2024-01-02"),
                       "Ada Example, Bob Example · Journal of Examples · 2024")
        XCTAssertEqual(PaperCardText.byline(authors: ["A", "B", "C", "D"], venue: nil, published: nil), "A, B, C et al.")
        XCTAssertEqual(PaperCardText.feedLine(PaperSummary(authors: ["Ada Example", "Bob Example"], published: "2024-01-02")),
                       "Ada Example et al. · 2024")
        XCTAssertNil(PaperCardText.feedLine(PaperSummary()))
    }

    func testWhyItemsSayWhereTheWordsAre() {
        let why = PaperWhyItem(predicate: "cited-in", text: nil, target: "alpha-project", snippet: "x", highlightStart: 0,
                               highlightEnd: 1, file: "REFERENCES.md", heading: "Retrieval", edited: "2026-09-01",
                               kind: "assistant", episode: "ep_1", start: 0, end: 1, stale: false)
        XCTAssertEqual(PaperCardText.label(why), "Cited in alpha-project")
        XCTAssertEqual(PaperCardText.whereLine(why), "REFERENCES.md › Retrieval · edited 2026-09-01 · written by an agent")
        XCTAssertEqual(PaperCardText.contextHeading(source: "arxiv", asOf: "2026-09-23"), "Context (from arXiv, as of 2026-09-23)")
        XCTAssertEqual(PaperCardText.contextHeading(source: "crossref", asOf: nil), "Context (from Crossref)")
    }

    func testAPaperRowDecodesAndIsFoundByAuthorArxivIdAndDoi() throws {
        let paper = try item(#", "kind": "paper", "paper": {"authors": ["Ada Example"], "arxivId": "2401.00001", "doi": "10.9999/alpha.2024"}"#)
        XCTAssertTrue(paper.isPaper)
        XCTAssertTrue(FeedViewModel.matches(paper, query: "ada"))
        XCTAssertTrue(FeedViewModel.matches(paper, query: "2401.00001"))
        XCTAssertTrue(FeedViewModel.matches(paper, query: "10.9999"))
        XCTAssertFalse(FeedViewModel.matches(paper, query: "zebra"))
        let plain = try item()
        XCTAssertFalse(plain.isPaper)
        XCTAssertNil(plain.paper)
        XCTAssertTrue(FeedViewModel.matches(plain, query: "alpha"))
    }

    func testTheDetailAndTheMediaBlockDecode() throws {
        let json = """
        {"entityId": "media-arxiv-2401-00001", "title": "Paper Alpha", "authors": ["Ada Example"], "sections": ["Retrieval"],
         "why": [{"predicate": "saved-because", "text": "the architecture", "snippet": "- [Paper Alpha] — the architecture",
                  "highlightStart": 18, "highlightEnd": 34, "file": "REFERENCES.md", "heading": "Retrieval",
                  "edited": "2026-09-01", "kind": "user", "episode": "ep_2026-09-01_001", "start": 40, "end": 56,
                  "stale": false}],
         "agentOnly": false, "context": "We study.", "contextSource": "arxiv", "contextAsOf": "2026-09-23",
         "absUrl": "https://arxiv.org/abs/2401.00001"}
        """
        let detail = try JSONDecoder().decode(PaperDetail.self, from: Data(json.utf8))
        XCTAssertEqual(detail.why.first?.id, "saved-because|ep_2026-09-01_001|40")
        let block = try JSONDecoder().decode(MediaBlock.self, from: Data(#"{"url": "https://arxiv.org/abs/2401.00001", "mediaType": "url", "kind": "paper"}"#.utf8))
        XCTAssertTrue(block.isPaper)
        let older = try JSONDecoder().decode(MediaBlock.self, from: Data(#"{"url": "https://example.com", "mediaType": "url"}"#.utf8))
        XCTAssertFalse(older.isPaper)
    }

    /// Decode tolerance (Global Constraints): only `entityId` — and, per why
    /// item, `predicate` + `episode` — are required, so a partial span still
    /// renders as a plain quote instead of dropping the card.
    func testAMinimalDetailStillDecodes() throws {
        let json = #"{"entityId": "media-doi-0123456789", "why": [{"predicate": "cited-in", "episode": "ep_1"}]}"#
        let detail = try JSONDecoder().decode(PaperDetail.self, from: Data(json.utf8))
        XCTAssertEqual(detail.title, "media-doi-0123456789")
        XCTAssertEqual(detail.authors, [])
        XCTAssertEqual(detail.sections, [])
        XCTAssertFalse(detail.agentOnly)
        XCTAssertNil(detail.context)
        let why = try XCTUnwrap(detail.why.first)
        XCTAssertEqual(why.snippet, "")
        XCTAssertEqual(why.highlightStart, -1)
        // Never defaulted to "user" — a partial payload is not credited to the owner.
        XCTAssertEqual(why.kind, "reasoning")
        XCTAssertFalse(why.stale)
        XCTAssertEqual(PaperCardText.whereLine(why), "a note")
        let bare = try JSONDecoder().decode(PaperSummary.self, from: Data("{}".utf8))
        XCTAssertEqual(bare, PaperSummary())
    }

    /// Task 7 review r1 — the card opens on the graph-node stub, whose `media`
    /// is nil; it must still ask for the paper detail, or a first open shows
    /// neither the paper card nor a preview.
    func testTheCardAsksForPaperDetailFromTheGraphStub() throws {
        XCTAssertTrue(EntityDetailCard.wantsPaperDetail(type: .media, media: nil))
        let paper = try JSONDecoder().decode(MediaBlock.self, from: Data(#"{"url": "https://arxiv.org/abs/2401.00001", "mediaType": "url", "kind": "paper"}"#.utf8))
        XCTAssertTrue(EntityDetailCard.wantsPaperDetail(type: .media, media: paper))
        let link = try JSONDecoder().decode(MediaBlock.self, from: Data(#"{"url": "https://example.com", "mediaType": "url"}"#.utf8))
        XCTAssertFalse(EntityDetailCard.wantsPaperDetail(type: .media, media: link))
        XCTAssertFalse(EntityDetailCard.wantsPaperDetail(type: .project, media: nil))
    }
}
