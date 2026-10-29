import XCTest
@testable import CicadaApp

/// G227 follow-up (owner 2026-10-29) — merge two pages, split one, undo either. The split sheet's rules mirror
/// `page_join.reference_choice` exactly; the plan decodes as `GET /entities/{id}/split-plan` serves it; a join's
/// History row says what it did and offers Undo. Placeholders: `tool-x`, `bob-example`.
final class PageJoinTests: XCTestCase {

    private let planJSON = #"""
    {"entityId": "tool-x", "name": "Tool X", "type": "tool", "newId": "tool-x-2", "newName": "Tool X",
     "sentences": [{"n": 1, "section": "Summary", "text": "Tool X is a code editor.", "suggested": false, "reason": null},
                   {"n": 2, "section": "Summary", "text": "Tool X is also a program.", "suggested": true,
                    "reason": "a program, not the editor"}],
     "claims": [{"id": "clm_a", "text": "applied", "predicate": "applied-by", "object": "owner",
                 "episodes": ["e2"], "current": true}],
     "sources": [{"ref": "https://program.example/", "predicate": null, "label": null}],
     "conversations": [{"id": "e1", "title": null, "date": "2026-05-01"}, {"id": "e2", "title": null, "date": null}],
     "references": [{"pageId": "bob-example", "name": "Bob Example", "claims": 1, "links": 1, "episodes": ["e2"],
                     "suggested": "ask"}],
     "suggested": true}
    """#

    private func plan() throws -> SplitPlan {
        try JSONDecoder().decode(SplitPlan.self, from: Data(planJSON.utf8))
    }

    func test_thePlanDecodes_andItsSuggestionsArePreTicked_neverMore() throws {
        let p = try plan()
        let start = SplitSelection.starting(from: p)
        XCTAssertEqual(start.sentences, [2])
        XCTAssertTrue(start.claims.isEmpty && start.episodes.isEmpty, "only the read's sentences are pre-ticked")
        XCTAssertEqual(start.name, "Tool X")
        XCTAssertEqual(start.type, "tool")
    }

    func test_aLinkFollowsItsEvidence_untilThePersonSays() throws {
        let p = try plan()
        var s = SplitSelection.starting(from: p)
        let bob = p.references[0]
        XCTAssertEqual(s.choice(for: bob, plan: p), .stay, "its conversation stays while nothing moves")
        s.episodes = ["e2"]
        XCTAssertEqual(s.choice(for: bob, plan: p), .new, "every conversation it rests on moved")
        s.references["bob-example"] = .stay
        XCTAssertEqual(s.choice(for: bob, plan: p), .stay, "the person's word outranks the evidence")
    }

    func test_referenceChoiceNeverGuesses() {
        XCTAssertEqual(SplitLinkChoice.from(episodes: ["e2"], moved: ["e2"], staying: ["e1"]), .new)
        XCTAssertEqual(SplitLinkChoice.from(episodes: ["e1"], moved: ["e2"], staying: ["e1"]), .stay)
        XCTAssertEqual(SplitLinkChoice.from(episodes: ["e1", "e2"], moved: ["e2"], staying: ["e1"]), .ask)
        XCTAssertEqual(SplitLinkChoice.from(episodes: [], moved: ["e2"], staying: ["e1"]), .ask)
    }

    func test_theBodyCarriesOnlyWhatWasPicked_andOnlyTheLinksThePersonSettled() throws {
        var s = SplitSelection.starting(from: try plan())
        s.claims = ["clm_a"]
        s.references = ["bob-example": .new, "alpha-project": .ask]
        s.name = "  Tool X  "
        let body = s.body
        XCTAssertEqual(body["sentences"] as? [Int], [2])
        XCTAssertEqual(body["claims"] as? [String], ["clm_a"])
        XCTAssertEqual(body["references"] as? [String: String], ["bob-example": "new"])
        XCTAssertEqual(body["name"] as? String, "Tool X")
        XCTAssertFalse(SplitSelection().body.keys.contains("name"))
        XCTAssertTrue(SplitSelection().isEmpty)
    }

    func test_aJoinRowSaysWhatItDid_andOffersUndo() throws {
        let json = #"""
        [{"date": "2026-10-29", "changeType": "updated", "description": "", "author": "user", "authorKind": "user",
          "commitHash": "abc", "sessions": [], "join": "split", "undoable": true},
         {"date": "2026-10-29", "changeType": "updated", "description": "", "author": "user", "commitHash": "def",
          "sessions": []}]
        """#
        let rows = try JSONDecoder().decode([EntityHistoryEntry].self, from: Data(json.utf8))
        XCTAssertEqual(rows[0].join, "split")
        XCTAssertTrue(rows[0].undoable)
        XCTAssertTrue(HistoryRowWords.sentence(rows[0]).hasSuffix(Copy.Graph.historySplit))
        XCTAssertNil(rows[1].join, "an older backend's row decodes with no join")
        XCTAssertFalse(rows[1].undoable)
    }

    func test_theJoinAnswerDecodes() throws {
        let json = #"{"kind": "undo", "entityId": "tool-x", "otherId": null, "commit": "abc", "restored": ["tool-x-2"], "repointed": []}"#
        let answer = try JSONDecoder().decode(PageJoinAnswer.self, from: Data(json.utf8))
        XCTAssertEqual(answer.restored, ["tool-x-2"])
    }
}
