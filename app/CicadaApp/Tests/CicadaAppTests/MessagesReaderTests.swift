import XCTest
@testable import CicadaApp

/// G179 — the app's Messages reader against a synthetic `chat.db` (`SyntheticChatDB`). What may never cross: another
/// chat's words, a group chat, the handle (a phone number), an attachment's path.
final class MessagesReaderTests: XCTestCase {
    private var synthetic: SyntheticChatDB!
    private var dir: URL { synthetic.dir }
    private var dbURL: URL { synthetic.url }

    override func setUpWithError() throws { synthetic = try SyntheticChatDB() }
    override func tearDownWithError() throws { synthetic.close() }

    private func exec(_ sql: String, _ values: [Any?] = []) { synthetic.exec(sql, values) }
    @discardableResult
    private func chat(_ handle: String, style: Int = 45, name: String = "") -> Int64 {
        synthetic.chat(handle, style: style, name: name)
    }
    @discardableResult
    private func message(_ chat: Int64, minute: Int, fromMe: Bool, text: String?, bodyOnly: Bool = false,
                         tapback: Bool = false, attachment: String? = nil) -> Int64 {
        synthetic.message(chat, minute: minute, fromMe: fromMe, text: text, bodyOnly: bodyOnly, tapback: tapback,
                          attachment: attachment)
    }
    private func archived(_ text: String) -> Data { SyntheticChatDB.archived(text) }

    private func seed() -> (instinct: Int64, other: Int64) {
        let instinct = chat("+15550000001")
        let other = chat("+15550000003")
        chat("+15550000009", style: 43, name: "A group")   // never listed in this slice
        message(instinct, minute: 0, fromMe: true, text: "Plan the alpha-project launch?")
        message(instinct, minute: 1, fromMe: false, text: "Sure — I can draft it.", bodyOnly: true)
        message(instinct, minute: 2, fromMe: true, text: "Loved “Sure — I can draft it.”", tapback: true)
        message(instinct, minute: 3, fromMe: false, text: "\u{FFFC}Here is the plan.", attachment: "plan.png")
        message(other, minute: 5, fromMe: false, text: "CANARY-other conversation")
        return (instinct, other)
    }

    private func object(_ pass: MessagesPass) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: pass.json) as? [String: Any])
    }

    // MARK: tests

    func testTheListIsOneToOneChatsWithCountsAndNoWords() throws {
        let (instinct, other) = seed()
        let listed = try MessagesReader(database: dbURL).conversations()
        XCTAssertEqual(Set(listed.map(\.chatRowId)), [instinct, other], "a group chat is never listed")
        let row = try XCTUnwrap(listed.first { $0.chatRowId == instinct })
        XCTAssertEqual(row.fromMe, 1, "a tapback is not a message")
        XCTAssertEqual(row.fromThem, 2)
        XCTAssertEqual(row.id, MessagesReader.conversationId(chatGuid: "iMessage;-;+15550000001"))
        XCTAssertEqual(row.id.count, 24)
        XCTAssertFalse(row.id.contains("5550000001"))
        XCTAssertNotNil(row.lastActivity)
    }

    func testOnlyTheTickedChatIsReadAndNothingPrivateCrosses() throws {
        let (instinct, _) = seed()
        let reader = MessagesReader(database: dbURL)
        let conversation = try XCTUnwrap(try reader.conversations().first { $0.chatRowId == instinct })
        let pass = try reader.read(conversation, name: "Instinct", since: MessagesCursor())
        let text = String(decoding: pass.json, as: UTF8.self)
        XCTAssertFalse(text.contains("CANARY"), "another chat's words or an attachment's path crossed")
        XCTAssertFalse(text.contains("5550000001"), "the handle never leaves the app")
        let body = try object(pass)
        let messages = try XCTUnwrap(body["messages"] as? [[String: Any]])
        XCTAssertEqual(messages.count, 4, "the tapback row crosses — the backend skips it, and counts it")
        let bodyOnly = messages[1]
        XCTAssertNil(bodyOnly["text"])
        let blob = try XCTUnwrap(Data(base64Encoded: try XCTUnwrap(bodyOnly["attributedBody"] as? String)))
        XCTAssertEqual(blob, archived("Sure — I can draft it."))
        let attachments = try XCTUnwrap(messages[3]["attachments"] as? [[String: Any]])
        XCTAssertEqual(attachments.first?["name"] as? String, "plan.png")
        XCTAssertEqual(attachments.first?["mimeType"] as? String, "image/png")
        let conv = try XCTUnwrap(body["conversation"] as? [String: Any])
        XCTAssertEqual(conv["id"] as? String, conversation.id)
        XCTAssertEqual(conv["name"] as? String, "Instinct")
        XCTAssertEqual(conv["fromThem"] as? Int, 2)
        XCTAssertEqual(pass.cursor.rowid, messages.compactMap { ($0["rowid"] as? NSNumber)?.int64Value }.max())
    }

    func testTheCursorReadsOnlyNewRowsThenEditsAndUnsends() throws {
        let (instinct, _) = seed()
        let reader = MessagesReader(database: dbURL)
        let conversation = try XCTUnwrap(try reader.conversations().first { $0.chatRowId == instinct })
        let first = try reader.read(conversation, name: "Instinct", since: MessagesCursor())
        XCTAssertEqual(try reader.read(conversation, name: "Instinct", since: first.cursor).count, 0)
        let added = message(instinct, minute: 10, fromMe: true, text: "One more thing.")
        let second = try reader.read(conversation, name: "Instinct", since: first.cursor)
        XCTAssertEqual(second.count, 1)
        XCTAssertEqual(second.cursor.rowid, added)
        // An edit keeps its old ROWID: the change watermark finds it.
        exec("UPDATE message SET text = 'Plan the launch, please.', date_edited = ? WHERE ROWID = 1", [Int64(900_000_000_000_000_000)])
        let edited = try reader.read(conversation, name: "Instinct", since: second.cursor)
        XCTAssertEqual(edited.count, 1)
        XCTAssertEqual(try object(edited)["messages"].flatMap { ($0 as? [[String: Any]])?.first?["rowid"] as? NSNumber }?.int64Value, 1)
        XCTAssertEqual(edited.cursor.changed, 900_000_000_000_000_000)
        XCTAssertEqual(try reader.read(conversation, name: "Instinct", since: edited.cursor).count, 0)
    }

    func testABatchLimitSaysThereIsMore() throws {
        let (instinct, _) = seed()
        var reader = MessagesReader(database: dbURL)
        reader.batchLimit = 2
        let conversation = try XCTUnwrap(try reader.conversations().first { $0.chatRowId == instinct })
        let pass = try reader.read(conversation, name: "Instinct", since: MessagesCursor())
        XCTAssertEqual(pass.count, 2)
        XCTAssertTrue(pass.hasMore)
        let rest = try reader.read(conversation, name: "Instinct", since: pass.cursor)
        XCTAssertEqual(rest.count, 2)
        // A full batch cannot know it was the last; the next read says so by finding nothing.
        XCTAssertEqual(try reader.read(conversation, name: "Instinct", since: rest.cursor).count, 0)
    }

    func testARefusedReadIsTheFullDiskAccessFixAndAnAbsentOneIsMissing() throws {
        _ = seed()
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: dbURL.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: dbURL.path) }
        XCTAssertThrowsError(try MessagesReader(database: dbURL).conversations()) { error in
            guard case .notReadable(.messagesDatabase, _)? = error as? BrowserFileError else {
                return XCTFail("expected the Full Disk Access fix, got \(error)")
            }
        }
        let gone = dir.appendingPathComponent("nothing-here.db")
        XCTAssertThrowsError(try MessagesReader(database: gone).conversations()) { error in
            guard case .missing(.messagesDatabase, _)? = error as? BrowserFileError else {
                return XCTFail("expected missing, got \(error)")
            }
        }
    }
}
