import XCTest
@testable import CicadaApp

final class AskHistoryTests: XCTestCase {
    private func entry(_ question: String, _ date: Date = Date()) -> AskHistoryEntry {
        AskHistoryEntry(question: question, askedAt: date, answer: nil)
    }

    func testPushIsMostRecentFirst() {
        var history: [AskHistoryEntry] = []
        history = AskHistory.push(entry("first"), into: history)
        history = AskHistory.push(entry("second"), into: history)
        history = AskHistory.push(entry("third"), into: history)
        XCTAssertEqual(history.map(\.question), ["third", "second", "first"])
    }

    func testPushCapsAtMax20() {
        var history: [AskHistoryEntry] = []
        for i in 0..<25 {
            history = AskHistory.push(entry("q\(i)"), into: history)
        }
        XCTAssertEqual(history.count, AskHistory.maxEntries)
        // Most recent 20 survive, most-recent-first.
        XCTAssertEqual(history.first?.question, "q24")
        XCTAssertEqual(history.last?.question, "q5")
    }

    func testPushDedupesByQuestionCaseInsensitiveTrimmed() {
        var history: [AskHistoryEntry] = []
        history = AskHistory.push(entry("What is my thesis about?"), into: history)
        history = AskHistory.push(entry("Who is my supervisor?"), into: history)
        // Same question, different casing/whitespace: replaces the earlier
        // entry rather than appearing twice, and moves to the front.
        history = AskHistory.push(entry("  what is my thesis about?  "), into: history)
        XCTAssertEqual(history.count, 2)
        XCTAssertEqual(history.first?.question, "  what is my thesis about?  ")
        XCTAssertEqual(history.filter {
            $0.question.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "what is my thesis about?"
        }.count, 1)
    }

    func testPushDedupeThenCapKeepsMostRecent20Unique() {
        var history: [AskHistoryEntry] = []
        for i in 0..<20 {
            history = AskHistory.push(entry("q\(i)"), into: history)
        }
        // Re-ask an existing question — should not grow past 20, and should
        // move to the front.
        history = AskHistory.push(entry("q5"), into: history)
        XCTAssertEqual(history.count, 20)
        XCTAssertEqual(history.first?.question, "q5")
    }

    // MARK: - AskResponse tolerant decoding

    func testAskResponseDecodesWithMissingGaps() throws {
        let json = """
        {"answer": "Your thesis is about memory consolidation.", "confidence": 0.82,
         "citations": [{"entityId": "e1", "entityName": "Thesis", "filePath": "entities/thesis.md", "snippet": "..."}]}
        """.data(using: .utf8)!
        let decoded = try JSONDecoder().decode(AskResponse.self, from: json)
        XCTAssertEqual(decoded.answer, "Your thesis is about memory consolidation.")
        XCTAssertEqual(decoded.confidence, 0.82)
        XCTAssertEqual(decoded.citations.count, 1)
        XCTAssertEqual(decoded.citations.first?.sourceEpisodes, [])
        XCTAssertEqual(decoded.gaps, [])
        XCTAssertEqual(decoded.usedEntities, [])
    }

    func testAskResponseDecodesWithMissingConfidenceAndCitations() throws {
        let json = """
        {"answer": "I don't have enough information."}
        """.data(using: .utf8)!
        let decoded = try JSONDecoder().decode(AskResponse.self, from: json)
        XCTAssertEqual(decoded.answer, "I don't have enough information.")
        XCTAssertEqual(decoded.confidence, 0)
        XCTAssertEqual(decoded.citations, [])
        XCTAssertEqual(decoded.gaps, [])
    }

    func testAskHistoryEntryRoundTripsThroughJSON() throws {
        let original = AskHistoryEntry(
            question: "what is my thesis about?",
            askedAt: Date(timeIntervalSince1970: 1_700_000_000),
            answer: AskResponse(answer: "Memory.", confidence: 0.9)
        )
        let data = try JSONEncoder().encode([original])
        let decoded = try JSONDecoder().decode([AskHistoryEntry].self, from: data)
        XCTAssertEqual(decoded.first?.question, original.question)
        XCTAssertEqual(decoded.first?.answer, original.answer)
    }
}
