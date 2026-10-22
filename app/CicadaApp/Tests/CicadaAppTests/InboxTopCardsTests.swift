import XCTest
@testable import CicadaApp

/// G205 / G61 — an agent request and the grouped Where-to-check review decode, and sit above the questions.
final class InboxTopCardsTests: XCTestCase {
    private func decode(_ json: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    func testAnAgentRequestDecodesItsAgentSiteAndNotificationWords() throws {
        let item = try decode("""
        {"id": "agent-req-1", "kind": "agent_request", "requiredInput": "choice", "title": "Sign in to example.com",
         "options": [{"key": "done", "label": "I signed in"}, {"key": "dismiss", "label": "Not now"}],
         "request": {"agent": "claude-code", "agentName": "Claude Code", "umbrella": "anthropic", "logo": "claude",
                     "site": "example.com", "reason": "to read the post you talked about",
                     "notification": {"title": "Claude Code needs you", "body": "Sign in to example.com",
                                      "openUrl": "https://example.com/post"}}}
        """)
        XCTAssertEqual(item.kind, .agentRequest)
        XCTAssertEqual(item.request?.agentName, "Claude Code")
        XCTAssertEqual(item.request?.notification?.openUrl, "https://example.com/post")
        XCTAssertTrue(item.isTopCard)
    }

    func testTheGroupedReviewDecodesItsRowsAndAOneRowQuestionStaysAQuestion() throws {
        let review = try decode("""
        {"id": "inbox-9", "kind": "clarification", "requiredInput": "choice", "title": "Confirm 2 links",
         "asks": "sources", "review": true,
         "rows": [{"id": "r1", "page": "bob-example", "pageName": "Bob", "pageType": "person",
                   "ref": "https://github.com/bob-example", "linkKind": "github", "label": "github.com/bob-example",
                   "addedBy": "cicada", "evidence": {"episode": "ep-1", "start": 4, "end": 30, "kind": "user"}},
                  {"id": "r2", "page": "alpha-project", "ref": "https://example.com", "linkKind": "website"},
                  {"page": "missing-id"}]}
        """)
        XCTAssertTrue(review.isWhereToCheckReview)
        XCTAssertEqual(review.rows?.count, 2, "a row this build cannot read is dropped alone")
        XCTAssertEqual(WhereToCheckReviewCard.evidenceWords(review.rows![0]),
                       "https://github.com/bob-example\n\(Copy.WhereToCheck.fromYou)")
        let single = try decode("""
        {"id": "inbox-10", "kind": "clarification", "requiredInput": "choice", "title": "Is this their GitHub?",
         "asks": "sources", "rows": [{"id": "r1", "page": "bob-example", "ref": "https://github.com/bob-example"}]}
        """)
        XCTAssertFalse(single.isTopCard, "a one-row item is an ordinary question")
    }

    func testAnOlderPayloadStillDecodes() throws {
        let item = try decode("""
        {"id": "inbox-1", "kind": "decay", "requiredInput": "choice", "title": "Still true?"}
        """)
        XCTAssertNil(item.request)
        XCTAssertNil(item.rows)
        XCTAssertFalse(item.isTopCard)
    }

    func testLinkKindsWearAGlyphAndAnUnknownOneTheGlobe() {
        XCTAssertEqual(LinkKindGlyph.symbol("github"), "chevron.left.forwardslash.chevron.right")
        XCTAssertEqual(LinkKindGlyph.symbol("something-new"), "globe")
    }
}

/// G61 — the entity card's chip row shows taken links only; a waiting proposal and a note do not make a chip.
final class WhereToCheckChipsTests: XCTestCase {
    func testOnlyLinksThatAreNotWaitingBecomeChips() throws {
        let json = """
        {"entityId": "bob-example", "sources": [
          {"ref": "https://github.com/bob-example", "kind": "url", "addedBy": "user", "addedAt": "2026-10-22",
           "linkKind": "github", "label": "github.com/bob-example", "proposed": false},
          {"ref": "https://x.com/bob-example", "kind": "url", "addedBy": "cicada", "addedAt": "2026-10-22",
           "linkKind": "x", "proposed": true},
          {"ref": "Ask bob-example", "kind": "note", "addedBy": "user", "addedAt": "2026-10-22"}]}
        """
        let list = try JSONDecoder().decode(EntitySourceList.self, from: Data(json.utf8))
        let chips = WhereToCheckChips.chips(list.sources)
        XCTAssertEqual(chips.map(\.ref), ["https://github.com/bob-example"])
        XCTAssertNil(chips.first?.iconSite, "a person's page never carries a site icon (G159)")
    }
}
