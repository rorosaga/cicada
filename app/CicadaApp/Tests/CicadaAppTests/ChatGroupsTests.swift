import XCTest
@testable import CicadaApp

/// Owner 2026-11-23 — one card per chat on the Sleep page: its waiting sittings together, its messages counted once.
final class ChatGroupsTests: XCTestCase {
    private func item(_ id: String, chat: String? = nil, name: String? = nil, messages: Int = 0, processed: Bool = false,
                      group: Bool = false) throws -> EpisodeQueueItem {
        var json: [String: Any] = ["id": id, "timestamp": "2026-11-23T10:00:00Z", "source": "imessage",
                                   "origin": "imessage", "title": id, "preview": "", "processed": processed]
        if let chat {
            var c: [String: Any] = ["id": chat, "messages": messages, "group": group]
            if let name { c["name"] = name }
            json["chat"] = c
        }
        return try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    func testAChatsSittingsStandAsOneEntryWhereItsNewestStood() throws {
        let items = [try item("s3", chat: "bob", name: "bob-example", messages: 5),
                     try item("note"),
                     try item("s2", chat: "alpha", name: "alpha-project", messages: 40, group: true),
                     try item("s1", chat: "bob", name: "bob-example", messages: 7)]
        let entries = ChatGroups.entries(items)
        XCTAssertEqual(entries.map(\.id), ["chat:bob", "note", "chat:alpha"])
        guard case .chat(let bob) = entries[0], case .chat(let alpha) = entries[2] else { return XCTFail("chats") }
        XCTAssertEqual(bob.sittings.map(\.id), ["s3", "s1"], "newest first")
        XCTAssertEqual(bob.messages, 12, "the chat's messages, counted once across its sittings")
        XCTAssertEqual(ChatGroups.title(bob), "bob-example")
        XCTAssertTrue(alpha.group)
        XCTAssertEqual(alpha.messages, 40)
    }

    func testAReadSittingWaitsForNothingAndAnUnnamedChatSaysWhatItIs() throws {
        let entries = ChatGroups.entries([try item("s2", chat: "x", messages: 3),
                                          try item("s1", chat: "x", messages: 9, processed: true)])
        guard case .chat(let chat) = entries[0] else { return XCTFail("a chat") }
        XCTAssertEqual(chat.messages, 3, "only what still waits")
        XCTAssertEqual(chat.waiting.map(\.id), ["s2"])
        XCTAssertEqual(ChatGroups.title(chat), "Unnamed chat")
        let group = ChatGroup(id: "g", name: nil, group: true, selfChat: false, sittings: [])
        XCTAssertEqual(ChatGroups.title(group), "Unnamed group")
        XCTAssertEqual(ChatGroups.title(ChatGroup(id: "me", name: nil, group: false, selfChat: true, sittings: [])),
                       "Notes to yourself")
    }

    func testTheSecondLineSaysHowManyAndHowLongAgoNeverHowItIsStored() throws {
        let now = ISO8601DateFormatter().date(from: "2026-11-23T12:00:00Z")!
        let us = Locale(identifier: "en_US")
        let two = ChatGroups.entries([try item("s2", chat: "bob", messages: 1_200), try item("s1", chat: "bob", messages: 4)])
        guard case .chat(let chat) = two[0] else { return XCTFail("a chat") }
        XCTAssertEqual(ChatGroups.meta(chat, now: now, locale: us), ["1,204 messages", "2h ago"],
                       "a sitting is how a chat is stored, never something the card says")
        let one = ChatGroups.entries([try item("s1", chat: "bob", messages: 1)])
        guard case .chat(let single) = one[0] else { return XCTFail("a chat") }
        XCTAssertEqual(ChatGroups.meta(single, now: now, locale: us), ["1 message", "2h ago"])
    }

    func testEverythingElseIsACardEachAndAnOlderBackendGroupsNothing() throws {
        let entries = ChatGroups.entries([try item("a"), try item("b")])
        XCTAssertEqual(entries.map(\.id), ["a", "b"])
    }
}
