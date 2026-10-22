import XCTest
@testable import CicadaApp

/// 2026-10-19 — Ask shows the conversations its answer used that no page cites (`POST /ask` `conversations`, the
/// search leg), each opening in the Reader. Synthetic ids and titles only.
final class AskConversationsTests: XCTestCase {
    private func decode(_ json: String) throws -> AskResponse {
        try JSONDecoder().decode(AskResponse.self, from: Data(json.utf8))
    }

    func testTheFieldDecodesInTheBackendsOrder() throws {
        let answer = try decode("""
        {"answer": "It moved to Thursdays.", "confidence": 0.7, "citations": [], "gaps": [], "usedEntities": [],
         "conversations": [
           {"episodeId": "ep_2026-10-02_003", "title": "Planning alpha-project", "day": "2026-10-02"},
           {"episodeId": "ep_2026-09-28_001", "title": "", "day": "2026-09-28"}
         ]}
        """)
        XCTAssertEqual(answer.conversationRows.map(\.episodeId), ["ep_2026-10-02_003", "ep_2026-09-28_001"])
        XCTAssertEqual(answer.conversationRows.first?.title, "Planning alpha-project")
        XCTAssertEqual(answer.conversationRows.first?.day, "2026-10-02")
    }

    func testAnOlderBackendWithoutTheFieldShowsNothing() throws {
        let answer = try decode("""
        {"answer": "No idea.", "confidence": 0.1, "citations": [], "gaps": ["the date"], "usedEntities": []}
        """)
        XCTAssertTrue(answer.conversations.isEmpty)
        XCTAssertTrue(answer.conversationRows.isEmpty, "no section is drawn")
        XCTAssertEqual(answer.gaps, ["the date"], "the rest of the answer still decodes")
    }

    func testAMalformedFieldNeverBlanksTheAnswer() throws {
        let answer = try decode("""
        {"answer": "Still here.", "confidence": 0.5, "conversations": "not a list"}
        """)
        XCTAssertEqual(answer.answer, "Still here.")
        XCTAssertTrue(answer.conversationRows.isEmpty)
        let partial = try decode("""
        {"answer": "x", "confidence": 0.5, "conversations": [{"title": "no id"}, {"episodeId": "ep_1"},
                                                            {"episodeId": "ep_1", "title": "again"}]}
        """)
        XCTAssertEqual(partial.conversationRows.map(\.episodeId), ["ep_1"],
                       "a row with nothing to open is dropped; a repeated id shows once")
    }

    func testAnAnswerCachedInHistoryKeepsItsConversations() throws {
        let answer = AskResponse(answer: "a", confidence: 0.5,
                                 conversations: [AskConversation(episodeId: "ep_2026-10-02_003", title: "T", day: "2026-10-02")])
        let entry = AskHistoryEntry(question: "q", askedAt: Date(timeIntervalSince1970: 0), answer: answer)
        let round = try JSONDecoder().decode(AskHistoryEntry.self, from: JSONEncoder().encode(entry))
        XCTAssertEqual(round.answer?.conversations, answer.conversations)

        let legacy = try JSONDecoder().decode(AskHistoryEntry.self, from: Data("""
        {"question": "q", "answer": {"answer": "a", "confidence": 0.5}}
        """.utf8))
        XCTAssertEqual(legacy.answer?.conversations, [], "history written before the field still decodes")
    }

    func testARowOpensTheConversationInTheReaderFromTheTop() {
        let conversation = AskConversation(episodeId: "ep_2026-10-02_003", title: "Planning alpha-project", day: "2026-10-02")
        let action = AskConversationRow.primary(conversation, readerAvailable: true)
        XCTAssertEqual(action, .open(ReaderTarget(episode: "ep_2026-10-02_003", knownTitle: "Planning alpha-project")))
        guard case .open(let target) = action else { return XCTFail("a click opens the Reader") }
        XCTAssertEqual(target.focus, .none, "the whole conversation, from the top")
        XCTAssertEqual(target.query, .none)

        let untitled = AskConversation(episodeId: "ep_2", title: "  ", day: "")
        XCTAssertEqual(AskConversationRow.primary(untitled, readerAvailable: true), .open(ReaderTarget(episode: "ep_2")),
                       "no known title rather than a blank one")
        XCTAssertEqual(AskConversationRow.primary(conversation, readerAvailable: false), .copy("ep_2026-10-02_003"),
                       "with no Reader (a preview), a click still does something")
    }

    func testARowIsNamedByTitleAndDayNeverByItsId() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let now = calendar.date(from: DateComponents(year: 2026, month: 10, day: 19))!
        // The locale is pinned here, never the runner's: a Mac in Spain reads "2 Oct", and so does this test's en_GB.
        let us = Locale(identifier: "en_US"), gb = Locale(identifier: "en_GB")
        XCTAssertEqual(AskConversationRow.day("2026-10-02", now: now, calendar: calendar, locale: us), "Oct 2")
        XCTAssertEqual(AskConversationRow.day("2025-03-14", now: now, calendar: calendar, locale: us), "Mar 14, 2025")
        XCTAssertEqual(AskConversationRow.day("2026-10-02", now: now, calendar: calendar, locale: gb), "2 Oct")
        XCTAssertEqual(AskConversationRow.day("2025-03-14", now: now, calendar: calendar, locale: gb), "14 Mar 2025")
        XCTAssertEqual(AskConversationRow.day("", now: now, calendar: calendar, locale: us), "")
        XCTAssertEqual(AskConversationRow.day("2026-13-40", now: now, calendar: calendar, locale: us), "", "never a raw string")

        let titled = AskConversation(episodeId: "ep_2026-10-02_003", title: "Planning alpha-project", day: "2026-10-02")
        XCTAssertEqual(AskConversationRow.title(titled), "Planning alpha-project")
        XCTAssertEqual(AskConversationRow.title(AskConversation(episodeId: "ep_9")), Copy.AskWords.untitledConversation)
        XCTAssertFalse(AskConversationRow.title(AskConversation(episodeId: "ep_9")).contains("ep_"), "DR-54")
        let help = AskConversationRow.help(titled)
        XCTAssertTrue(help.hasPrefix(Copy.AskWords.openConversationHint))
        XCTAssertTrue(help.hasSuffix("Episode ep_2026-10-02_003"), "DR-54: the id is reachable in .help")
    }
}
