import XCTest
@testable import CicadaApp

/// G227 follow-up (owner 2026-10-29) — merge in the app, separate with the person's agent, undo from History.
/// Placeholders: `tool-x`.
final class PageJoinTests: XCTestCase {

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

    func test_theJoinAnswerDecodes_andAnOlderOneWithoutRemoved() throws {
        let json = #"{"kind": "undo", "entityId": "tool-x", "otherId": null, "commit": "abc", "restored": [], "repointed": [], "removed": ["tool-x-2"]}"#
        XCTAssertEqual(try JSONDecoder().decode(PageJoinAnswer.self, from: Data(json.utf8)).removed, ["tool-x-2"])
        let older = #"{"kind": "merge", "entityId": "tool-x"}"#
        XCTAssertEqual(try JSONDecoder().decode(PageJoinAnswer.self, from: Data(older.utf8)).removed, [])
    }

    func test_theHandOffNamesThePageAndAsksBeforeSplitting() {
        let prompt = SeparateHandOff.prompt(id: "tool-x", name: "Tool X")
        XCTAssertTrue(prompt.contains("`tool-x`") && prompt.contains("Tool X"))
        XCTAssertTrue(prompt.contains("cicada_split_page") && prompt.contains("after I say yes"))
    }
}
