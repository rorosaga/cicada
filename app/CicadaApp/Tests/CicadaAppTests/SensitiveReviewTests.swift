import XCTest
@testable import CicadaApp

/// G235 — the one review decodes, sits above the questions, and says who read what in one line; a run says so in one more.
final class SensitiveReviewTests: XCTestCase {
    private func decode(_ json: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    private let review = """
    {"id": "inbox-7", "kind": "sensitive", "requiredInput": "choice", "title": "2 conversations may hold something sensitive",
     "replaced": 12,
     "sensitiveRows": [
       {"id": "s1", "episode": "ep_2026-11-01_001", "title": "Plans", "day": "2026-11-01", "kinds": ["password", "card"],
        "readBy": ["Claude plan"], "heldKinds": ["card"], "heldFrom": ["Claude plan"], "earlier": false},
       {"id": "s2", "episode": "ep_2026-10-01_001", "title": "A conversation", "day": "2026-10-01", "kinds": ["id"],
        "readBy": [], "heldFrom": [], "earlier": true},
       {"id": "s3", "episode": "ep_2026-09-01_001", "title": "Notes", "day": "2026-09-01", "kinds": ["bank"],
        "readBy": [], "heldKinds": ["bank"], "heldFrom": ["ChatGPT plan"], "earlier": false}]}
    """

    func testTheReviewIsACardAboveTheQuestionsAndNeverAQuestionRow() throws {
        let item = try decode(review)
        XCTAssertEqual(item.kind, .sensitive)
        XCTAssertTrue(item.isTopCard)
        XCTAssertEqual(item.sensitiveRows?.count, 3)
        XCTAssertEqual(item.replaced, 12)
    }

    func testARowSaysWhatKindAndWhoReadItInOneLine() throws {
        let rows = try XCTUnwrap(try decode(review).sensitiveRows)
        XCTAssertEqual(SensitiveRow.line(rows[0]), "A card number held back from Claude plan · A password read by Claude plan · Nov 1")
        XCTAssertEqual(SensitiveRow.line(rows[1]), "An ID number read by an earlier Sleep · Oct 1")
        XCTAssertEqual(SensitiveRow.line(rows[2]), "A bank account held back from ChatGPT plan · Sep 1")
    }

    func testAnOlderServersItemWithNoRowsStillDecodes() throws {
        let item = try decode(#"{"id": "inbox-1", "kind": "sensitive", "requiredInput": "choice", "title": "x"}"#)
        XCTAssertEqual(item.sensitiveRows, nil)
        XCTAssertEqual(item.replaced, nil)
    }

    func testARunSaysItInOneLineOnlyWhenItHasSomethingToSay() throws {
        XCTAssertEqual(Copy.Sensitive.runLine(conversations: 1, kinds: ["password"]), "1 conversation may hold a password")
        XCTAssertEqual(Copy.Sensitive.runLine(conversations: 3, kinds: ["password", "id"]),
                       "3 conversations may hold something sensitive")
        let quiet = try JSONDecoder().decode(SleepRunRef.self, from: Data(#"{"id": "d1"}"#.utf8))
        XCTAssertNil(quiet.sensitive)
        let said = try JSONDecoder().decode(SleepRunRef.self, from: Data(
            #"{"id": "d1", "sensitive": {"conversations": 2, "kinds": ["card"]}}"#.utf8))
        XCTAssertEqual(said.sensitive?.conversations, 2)
    }

    func testTheCopySaysPlainlyWhatStaysAndNeverAWordOfTheValue() {
        XCTAssertTrue(Copy.Sensitive.effect.contains("History keeps an older copy"))
        XCTAssertTrue(Copy.Sensitive.effect.contains("can't be unread"))
        XCTAssertEqual(Copy.Sensitive.kinds(["key"]), "A key")
    }
}
