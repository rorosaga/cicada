import XCTest
@testable import CicadaApp

/// app-fixes-1109 item 1 — *Answer* opens the chat on the lead question, with what the card is about from the record.
@MainActor
final class CatchupContextTests: XCTestCase {
    private func item(_ extra: String) throws -> InboxItem {
        let json = #"{"id":"inbox-1","kind":"merge_suggestion","requiredInput":"choice","title":"Are Alpha and Beta the same?","priority":0.5,"createdDate":"2026-11-01","entityId":"alpha","entityName":"Alpha","mergeTargetHint":"beta","mergeTargetDisplayName":"Beta"\#(extra)}"#
        return try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    func testAMergeSaysWhatEachPageSaysSideBySide() throws {
        let both = try item(#","subject":{"summary":"A synthetic tool for lamps."},"otherSubject":{"summary":"A synthetic library about boats."}"#)
        XCTAssertEqual(CatchupContext.summary(for: both), "Alpha: A synthetic tool for lamps.\nBeta: A synthetic library about boats.")
        let one = try item(#","subject":{"summary":"A synthetic tool for lamps."}"#)
        XCTAssertEqual(CatchupContext.summary(for: one), "Alpha: A synthetic tool for lamps.")
        XCTAssertNil(CatchupContext.summary(for: try item("")), "nothing on the record adds nothing")
    }

    func testAnswerOpensTheChatNotTheInboxList() throws {
        let dir = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Home/HomeSections.swift") })
        let source = try String(contentsOf: dir, encoding: .utf8)
        XCTAssertTrue(source.contains("startAnswer([lead.id]"), "Answer starts the chat on the lead question")
    }
}
