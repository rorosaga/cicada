import XCTest
@testable import CicadaApp

/// Design §4.7 (P5) — the inbox and Ask reach the same Reader: an inbox
/// cause opens on its mention (labelled derived unless it was an asserted
/// G118 span), and an answer's sources carry evidence chips.
final class ProvenanceEntryPointTests: XCTestCase {

    private func cause(_ json: String) throws -> InboxCause {
        try JSONDecoder().decode(InboxCause.self, from: Data(json.utf8))
    }

    // MARK: Inbox

    func testADerivedCauseOpensOnTheMentionWithNoHashAndStaysDerived() throws {
        // The excerpt window starts at 900; the mention is excerpt[30, 40).
        let c = try cause("""
        {"episodeId": "ep_2026-09-03_004", "harness": "claude-code", "conversationTitle": "Index choice",
         "excerpt": "…", "mentionOffsets": [[30, 40]], "start": 900, "end": 1300,
         "tier": "claim", "spanKind": "derived"}
        """)
        let target = c.readerTarget(subjectId: "alpha-project")
        XCTAssertEqual(target?.episode, "ep_2026-09-03_004")
        XCTAssertEqual(target?.focus, .span(start: 930, end: 940, hash: nil, derived: true),
                       "R-PB16 — start is the WINDOW's offset; the mention sits at start + m0")
        XCTAssertEqual(target?.subjectId, "alpha-project")
        XCTAssertEqual(target?.knownTitle, "Index choice")
        XCTAssertEqual(target?.knownHarness, "claude-code")
    }

    func testAnAssertedCauseLandsWashed() throws {
        let c = try cause("""
        {"episodeId": "ep_1", "excerpt": "…", "mentionOffsets": [[0, 5]], "start": 10, "tier": "item",
         "spanKind": "asserted"}
        """)
        XCTAssertEqual(c.readerTarget(subjectId: nil)?.focus, .span(start: 10, end: 15, hash: nil, derived: false))
    }

    func testACauseWithNoMentionOpensAtTheTopAndNoSourceOpensNothing() throws {
        let top = try cause(#"{"episodeId": "ep_1", "excerpt": "head", "start": 0, "tier": "entity"}"#)
        XCTAssertEqual(top.readerTarget(subjectId: "a")?.focus, ReaderTarget.Focus.none)
        let none = try cause(#"{"excerpt": "[ no source recorded ]", "tier": "none"}"#)
        XCTAssertNil(none.readerTarget(subjectId: "a"))
        let noEpisode = try cause(#"{"excerpt": "x", "tier": "claim", "mentionOffsets": [[0, 1]], "start": 0}"#)
        XCTAssertNil(noEpisode.readerTarget(subjectId: "a"))
    }

    // MARK: Ask

    func testAClaimHitCarriesItsStoredSpansAsChips() {
        let hit = AskCitation(entityId: "alpha-project", entityName: "Alpha project", filePath: "", snippet: "s",
                              sourceEpisodes: ["ep_9"], claimId: "clm_1",
                              evidence: [Evidence(episode: "ep_1", start: 1, end: 5, kind: .user, hash: "h")])
        XCTAssertEqual(hit.evidenceChips.map(\.kind), [.user])
    }

    func testAnEntityOnlyHitFallsBackToDerivedChipsAndNothingMeansNoRow() {
        let entity = AskCitation(entityId: "alpha-project", entityName: "Alpha project", filePath: "", snippet: "s",
                                 sourceEpisodes: ["ep_1", "ep_2"])
        XCTAssertEqual(entity.evidenceChips.map(\.kind), [.derived, .derived])
        let bare = AskCitation(entityId: "alpha-project", entityName: "Alpha project", filePath: "", snippet: "s")
        XCTAssertTrue(bare.evidenceChips.isEmpty)
    }
}
