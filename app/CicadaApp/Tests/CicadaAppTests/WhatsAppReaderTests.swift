import SQLite3
import XCTest
@testable import CicadaApp

/// G179 (2026-10-28) — a synthetic WhatsApp Desktop store (`api/tests/fixtures/whatsapp_tables.sql`, placeholder JIDs
/// and words): the list leaves status updates and channels out and never posts a number; a ticked chat's read carries
/// participant keys, the quoted-reply blob and a file's own name only; a delete for everyone inside the recheck window
/// is posted again; a tick starts live from the newest row; and the cost of one live update, file change → posted.
final class SyntheticWhatsAppStore {
    let dir: URL
    var url: URL { dir.appendingPathComponent("ChatStorage.sqlite") }
    private var db: OpaquePointer?
    private static let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    static var schemaURL: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("api/tests/fixtures/whatsapp_tables.sql")
    }

    init() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("SyntheticWhatsApp-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        XCTAssertEqual(sqlite3_open(url.path, &db), SQLITE_OK)
        XCTAssertEqual(sqlite3_exec(db, try String(contentsOf: Self.schemaURL, encoding: .utf8), nil, nil, nil), SQLITE_OK)
    }

    func close() {
        sqlite3_close(db)
        db = nil
        try? FileManager.default.removeItem(at: dir)
    }

    func exec(_ sql: String, _ values: [Any?] = []) {
        var stmt: OpaquePointer?
        XCTAssertEqual(sqlite3_prepare_v2(db, sql, -1, &stmt, nil), SQLITE_OK, String(cString: sqlite3_errmsg(db)))
        defer { sqlite3_finalize(stmt) }
        for (i, value) in values.enumerated() {
            let at = Int32(i + 1)
            switch value {
            case let v as Int: sqlite3_bind_int64(stmt, at, Int64(v))
            case let v as Int64: sqlite3_bind_int64(stmt, at, v)
            case let v as Double: sqlite3_bind_double(stmt, at, v)
            case let v as String: sqlite3_bind_text(stmt, at, v, -1, Self.transient)
            case let v as Data: _ = v.withUnsafeBytes { sqlite3_bind_blob(stmt, at, $0.baseAddress, Int32(v.count), Self.transient) }
            default: sqlite3_bind_null(stmt, at)
            }
        }
        XCTAssertEqual(sqlite3_step(stmt), SQLITE_DONE, String(cString: sqlite3_errmsg(db)))
    }

    var lastRow: Int64 { sqlite3_last_insert_rowid(db) }

    @discardableResult
    func session(_ jid: String, name: String, last: Double = 0) -> Int64 {
        exec("INSERT INTO ZWACHATSESSION (ZCONTACTJID, ZPARTNERNAME, ZLASTMESSAGEDATE) VALUES (?, ?, ?)", [jid, name, last])
        return lastRow
    }

    @discardableResult
    func member(_ session: Int64, jid: String, name: String) -> Int64 {
        exec("INSERT INTO ZWAGROUPMEMBER (ZCHATSESSION, ZMEMBERJID, ZCONTACTNAME) VALUES (?, ?, ?)", [session, jid, name])
        return lastRow
    }

    @discardableResult
    func message(_ session: Int64, _ stanza: String, at: Double, text: String?, fromMe: Bool = false, type: Int = 0,
                 member: Int64? = nil, media: (title: String?, path: String?, size: Int, metadata: Data?)? = nil) -> Int64 {
        exec("INSERT INTO ZWAMESSAGE (ZCHATSESSION, ZISFROMME, ZMESSAGEDATE, ZTEXT, ZMESSAGETYPE, ZSTANZAID, ZGROUPMEMBER) "
             + "VALUES (?, ?, ?, ?, ?, ?, ?)", [session, fromMe ? 1 : 0, at, text, type, stanza, member])
        let pk = lastRow
        if let media {
            exec("INSERT INTO ZWAMEDIAITEM (ZMESSAGE, ZTITLE, ZMEDIALOCALPATH, ZFILESIZE, ZMETADATA) VALUES (?, ?, ?, ?, ?)",
                 [pk, media.title, media.path, media.size, media.metadata])
        }
        return pk
    }
}

@MainActor
final class FakeChatSourcesAPI: ChatSourcesAPI {
    var ticked: Set<String> = []
    var history: Set<String> = []
    private(set) var posts: [[String: Any]] = []

    private func answer() -> ChatTickAnswer {
        ChatTickAnswer(conversations: ticked.map { ChatTickState(id: $0, ticked: true, history: history.contains($0)) })
    }

    func fetchChatTicks(source: String) async throws -> ChatTickAnswer { answer() }
    func describeChats(source: String, ids: [(id: String, group: Bool)]) async throws -> ChatTickAnswer { answer() }
    func updateChat(source: String, id: String, name: String?, group: Bool?, ticked: Bool?, history: Bool?) async throws
        -> ChatTickAnswer {
        if let ticked { if ticked { self.ticked.insert(id) } else { self.ticked.remove(id) } }
        if history == true { self.history.insert(id) }
        return answer()
    }

    func postWhatsApp(_ json: Data) async throws -> ChatSyncAnswer {
        posts.append(try XCTUnwrap(JSONSerialization.jsonObject(with: json) as? [String: Any]))
        return try JSONDecoder().decode(ChatSyncAnswer.self, from: Data(#"{"created": 1}"#.utf8))
    }
}

final class WhatsAppReaderTests: XCTestCase {
    var store: SyntheticWhatsAppStore!
    let friendJid = "15550000002@s.whatsapp.net"      // placeholder JIDs — never real numbers
    let groupJid = "120363000000000000@g.us"
    let now = Date(timeIntervalSinceReferenceDate: 800_000_000)

    override func setUpWithError() throws { store = try SyntheticWhatsAppStore() }
    override func tearDown() { store.close() }

    private func reader() -> WhatsAppReader {
        var r = WhatsAppReader(store: store.url)
        let now = self.now
        r.now = { now }
        return r
    }

    func testTheListLeavesStatusAndChannelsOutAndHashesTheJid() throws {
        store.session(friendJid, name: "Bob Example", last: 10)
        store.session(groupJid, name: "Weekend crew", last: 20)
        store.session("status@broadcast", name: "", last: 30)
        store.session("120363999999999999@newsletter", name: "A channel", last: 40)
        let chats = try reader().chats()
        XCTAssertEqual(chats.map(\.partnerName), ["Weekend crew", "Bob Example"])
        XCTAssertEqual(chats.map(\.group), [true, false])
        let friend = try XCTUnwrap(chats.last)
        XCTAssertEqual(friend.id, WhatsAppReader.chatId(jid: friendJid))
        XCTAssertFalse(friend.id.contains("1555"))
        XCTAssertEqual(friend.phoneHandle, "+15550000002")
    }

    func testATickedGroupsReadCarriesKeysTheQuoteAndAFileNameOnly() throws {
        let group = store.session(groupJid, name: "Weekend crew")
        let carol = store.member(group, jid: "15550000003@s.whatsapp.net", name: "Carol Example")
        let quote = Data([0x2A, 0x02]) + Data("G1".utf8)
        store.message(group, "G1", at: 799_000_000, text: "Who brings the demo?", member: carol)
        store.message(group, "G2", at: 799_000_060, text: "I will.", fromMe: true,
                      media: (title: nil, path: nil, size: 0, metadata: quote))
        store.message(group, "G3", at: 799_000_120, text: nil, type: 1, member: carol,
                      media: (title: nil, path: "Media/120363000000000000@g.us/a/b/IMG_0001.jpg", size: 1234, metadata: nil))
        let chat = try XCTUnwrap(reader().chats().first)
        let names = try reader().memberNames(chat)
        XCTAssertEqual(names["15550000003@s.whatsapp.net"], "Carol Example")
        let pass = try reader().read(chat, name: "Weekend crew", memberNames: names, since: 0)
        XCTAssertEqual(pass.count, 3)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: pass.json) as? [String: Any])
        let text = String(decoding: pass.json, as: UTF8.self)
        XCTAssertFalse(text.contains("1555"), "no number leaves the app")
        XCTAssertFalse(text.contains("Media/"), "no folder of a media path leaves the app")
        let messages = try XCTUnwrap(body["messages"] as? [[String: Any]])
        let key = WhatsAppReader.memberKey(chatJid: groupJid, memberJid: "15550000003@s.whatsapp.net")
        XCTAssertEqual(messages[0]["member"] as? String, key)
        XCTAssertNil(messages[1]["member"])
        XCTAssertEqual(messages[1]["metadata"] as? String, quote.base64EncodedString())
        XCTAssertEqual((messages[2]["media"] as? [String: Any])?["file"] as? String, "IMG_0001.jpg")
        let members = try XCTUnwrap((body["conversation"] as? [String: Any])?["members"] as? [[String: Any]])
        XCTAssertEqual(members.first?["name"] as? String, "Carol Example")
        XCTAssertEqual(pass.cursor, 3)
    }

    func testADeleteInsideTheRecheckWindowIsPostedAgain() throws {
        let friend = store.session(friendJid, name: "Bob Example")
        store.message(friend, "OLD", at: 700_000_000, text: "long ago")
        let pk = store.message(friend, "D1", at: now.timeIntervalSinceReferenceDate - 3600, text: "oops")
        let chat = try XCTUnwrap(reader().chats().first)
        store.exec("UPDATE ZWAMESSAGE SET ZMESSAGETYPE = 14, ZTEXT = NULL WHERE Z_PK = ?", [pk])
        let pass = try reader().read(chat, name: "", memberNames: [:], since: pk)
        let messages = try XCTUnwrap((JSONSerialization.jsonObject(with: pass.json) as? [String: Any])?["messages"]
                                     as? [[String: Any]])
        XCTAssertEqual(messages.map { $0["stanza"] as? String }, ["D1"], "the old row is not re-read; the recent one is")
        XCTAssertEqual(messages.first?["type"] as? Int, 14)
    }

    @MainActor
    func testATickIsLiveFromTheNewestRowAndHistoryOnlyOnAsk() async throws {
        let friend = store.session(friendJid, name: "Bob Example")
        store.message(friend, "H1", at: 700_000_000, text: "before the tick")
        let api = FakeChatSourcesAPI()
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "whatsapp-test-\(UUID().uuidString)"))
        let watcher = WhatsAppWatcher(api: api, reader: reader(), defaults: defaults, folder: store.dir,
                                      makeWatch: { _, _ in nil }, lookUpCards: { _ in [:] })
        await watcher.loadList()
        let chat = try XCTUnwrap(watcher.chats.first)
        try await watcher.setTicked(chat, true)
        XCTAssertEqual(api.posts.count, 0, "nothing before the tick is read")
        store.message(friend, "L1", at: now.timeIntervalSinceReferenceDate - 10, text: "after the tick")
        _ = try await watcher.syncNow()
        let live = try XCTUnwrap(api.posts.last?["messages"] as? [[String: Any]])
        XCTAssertEqual(live.map { $0["stanza"] as? String }, ["L1"])
        try await watcher.readHistory(chat)
        let all = api.posts.flatMap { ($0["messages"] as? [[String: Any]]) ?? [] }.compactMap { $0["stanza"] as? String }
        XCTAssertTrue(all.contains("H1"), "history read on the person's ask")
    }

    /// File change → posted (the app's half; the backend's is `test_chat_live.test_live_update_cost_p95`): one new
    /// message in a ticked chat of a 20,000-row store, read from an APFS clone.
    @MainActor
    func testLiveUpdateCostP95() async throws {
        let friend = store.session(friendJid, name: "Bob Example")
        store.exec("BEGIN")
        for i in 0..<20_000 {
            store.message(friend, "B\(i)", at: 700_000_000 + Double(i), text: "message \(i) with a few words in it")
        }
        store.exec("COMMIT")
        let api = FakeChatSourcesAPI()
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "whatsapp-test-\(UUID().uuidString)"))
        let watcher = WhatsAppWatcher(api: api, reader: reader(), defaults: defaults, folder: store.dir,
                                      makeWatch: { _, _ in nil }, lookUpCards: { _ in [:] })
        await watcher.loadList()
        try await watcher.setTicked(try XCTUnwrap(watcher.chats.first), true)
        var took: [Double] = []
        for i in 0..<20 {
            store.message(friend, "N\(i)", at: now.timeIntervalSinceReferenceDate - 5, text: "live \(i)")
            let started = ContinuousClock.now
            _ = try await watcher.syncNow()
            took.append(WhatsAppWatcher.seconds(ContinuousClock.now - started))
        }
        took.sort()
        let p95 = took[Int(Double(took.count) * 0.95) - 1]
        print("whatsapp app read+post p95 \(Int(p95 * 1000)) ms over \(took.count) (20,000-row store)")
        XCTAssertLessThan(p95, 1.0)
    }
}
