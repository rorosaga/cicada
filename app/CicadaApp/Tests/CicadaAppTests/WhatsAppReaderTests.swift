import CoreImage
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

    /// The statuses `telegramStatus` answers in order (the last repeats); empty = an empty status.
    var telegramStatuses: [TelegramStatusAnswer] = []
    func telegramStatus() async throws -> TelegramStatusAnswer {
        telegramStatuses.count > 1 ? telegramStatuses.removeFirst() : (telegramStatuses.first ?? TelegramStatusAnswer())
    }
    func telegramQR() async throws -> TelegramStatusAnswer {
        if holdQR { await withCheckedContinuation { qrGate = $0 } }
        return TelegramStatusAnswer(state: "qr", qrUrl: "tg://login?token=PLACEHOLDER")
    }
    private(set) var telegramConnects = 0
    /// Held while set: `telegramConnect` waits on it, as a send still in flight does.
    var holdConnect = false
    var connectGate: CheckedContinuation<Void, Never>?
    func telegramConnect(phone: String) async throws -> TelegramStatusAnswer {
        telegramConnects += 1
        if holdConnect { await withCheckedContinuation { connectGate = $0 } }
        return TelegramStatusAnswer(state: "code_sent")
    }
    func telegramCode(_ code: String) async throws -> TelegramStatusAnswer { TelegramStatusAnswer() }
    func telegramPassword(_ password: String) async throws -> TelegramStatusAnswer { TelegramStatusAnswer() }
    private(set) var telegramDisconnects = 0
    /// Held while set: `telegramQR` waits on it, as a QR request still in flight does.
    var qrGate: CheckedContinuation<Void, Never>?
    var holdQR = false
    func telegramDisconnect() async throws -> TelegramStatusAnswer {
        telegramDisconnects += 1
        return TelegramStatusAnswer()
    }
    func telegramChats() async throws -> TelegramChatsAnswer { TelegramChatsAnswer() }
    private(set) var telegramTicks: [(id: String, ticked: Bool, consent: Bool)] = []
    func telegramTick(id: String, name: String, ticked: Bool, consent: Bool) async throws -> ChatTickAnswer {
        telegramTicks.append((id, ticked, consent))
        if ticked && consent { self.ticked.insert(id) } else { self.ticked.remove(id) }
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

    override func setUpWithError() throws {
        ContactsTrap.install()   // never this Mac's Contacts service (#527 review)
        store = try SyntheticWhatsAppStore()
    }
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

    /// #502 review B1: a busy chat — more already-posted rows in the recheck window than a batch holds — still reaches
    /// its new row on the next pass.
    @MainActor
    func testABusyChatsNewRowIsAlwaysReached() async throws {
        let friend = store.session(friendJid, name: "Bob Example")
        store.exec("BEGIN")
        for i in 0..<600 { store.message(friend, "W\(i)", at: now.timeIntervalSinceReferenceDate - 3600 + Double(i), text: "w \(i)") }
        store.exec("COMMIT")
        let api = FakeChatSourcesAPI()
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "whatsapp-test-\(UUID().uuidString)"))
        let watcher = WhatsAppWatcher(api: api, reader: reader(), defaults: defaults, folder: store.dir,
                                      makeWatch: { _, _ in nil }, lookUpCards: { _ in [:] })
        await watcher.loadList()
        try await watcher.setTicked(try XCTUnwrap(watcher.chats.first), true)   // cursor at the newest of the 600
        store.message(friend, "NEW", at: now.timeIntervalSinceReferenceDate - 1, text: "the new one")
        _ = try await watcher.syncNow()
        let last = ((api.posts.last?["messages"] as? [[String: Any]]) ?? []).compactMap { $0["stanza"] as? String }
        XCTAssertTrue(last.contains("NEW"))
        XCTAssertLessThanOrEqual(last.count, 501, "the window re-read is bounded")
        XCTAssertEqual(watcher.status, .watching)
    }

    func testAGroupMentionNamesTheMemberAndNeverPostsTheNumber() {
        let names = ["15550000003@s.whatsapp.net": "Carol Example"]
        XCTAssertEqual(WhatsAppReader.namingMentions("@15550000003 and @15550009999 bring slides", names: names),
                       "@Carol Example and @someone bring slides")
        XCTAssertEqual(WhatsAppReader.namingMentions("email me@example.com, 2026", names: names), "email me@example.com, 2026")
    }

    /// #502 re-check: a one-to-one chat's @mentions are named at the source too, never posted as digits.
    func testAOneToOneMentionIsNamedAtTheSource() throws {
        let friend = store.session(friendJid, name: "Bob Example")
        store.message(friend, "M1", at: 799_000_000, text: "@15550000002 and @15550009999, see you", fromMe: true)
        let chat = try XCTUnwrap(reader().chats().first)
        let pass = try reader().read(chat, name: "Bob Example", memberNames: [:], since: 0)
        let text = String(decoding: pass.json, as: UTF8.self)
        XCTAssertFalse(text.contains("1555"))
        let messages = try XCTUnwrap((JSONSerialization.jsonObject(with: pass.json) as? [String: Any])?["messages"]
                                     as? [[String: Any]])
        XCTAssertEqual(messages.first?["text"] as? String, "@Bob Example and @someone, see you")
    }

    /// Ruling 47a amendment: a Telegram tick carries the consent the panel asked for; unticking withdraws it, and the
    /// confirmation names the chat.
    @MainActor
    func testATelegramTickCarriesConsentAndTheAskNamesTheChat() async throws {
        let api = FakeChatSourcesAPI()
        let model = TelegramChats(api: api)
        let chat = TelegramChatRow(id: String(repeating: "ab", count: 12), name: "Bob Example")
        await model.setTicked(chat, true, consent: true)
        await model.setTicked(chat, false, consent: true)
        XCTAssertEqual(api.telegramTicks.map(\.consent), [true, false], "an untick never carries consent")
        XCTAssertEqual(model.tickedIds, [])
        XCTAssertEqual(model.consentAsk(for: chat), "", "no sentence until the backend serves one")
    }

    /// Owner 2026-10-29: Telegram connects by a QR — the sheet draws the backend's link and follows the status until
    /// the phone accepts it; the drawn code carries exactly the link, inside a quiet zone.
    @MainActor
    func testTelegramConnectsByQRAndFollowsTheStatusUntilScanned() async throws {
        let api = FakeChatSourcesAPI()
        let model = TelegramChats(api: api)
        await model.startQR()
        XCTAssertTrue(model.showsQR)
        let link = try XCTUnwrap(model.status.qrUrl)
        api.telegramStatuses = [TelegramStatusAnswer(state: "qr", qrUrl: "tg://login?token=NEXT"),
                                TelegramStatusAnswer(state: "connected")]
        await model.followQR(every: .milliseconds(1))
        XCTAssertTrue(model.connected)
        XCTAssertFalse(model.showsQR)
        let image = try XCTUnwrap(TelegramQRCode.image(for: link))
        let cg = try XCTUnwrap(image.cgImage(forProposedRect: nil, context: nil, hints: nil))
        let found = try XCTUnwrap(CIDetector(ofType: CIDetectorTypeQRCode, context: nil, options: nil)?
            .features(in: CIImage(cgImage: cg)).compactMap { ($0 as? CIQRCodeFeature)?.messageString })
        XCTAssertEqual(found, [link], "the code says the link and nothing else")
        XCTAssertEqual(image.size.width.truncatingRemainder(dividingBy: 8), 0, "whole modules, quiet zone included")
    }

    /// #547 review 2/3: closing the sheet while the QR is still being asked for stops it when it answers; closing at a
    /// waiting password stops that too; a connected session is never touched.
    @MainActor
    func testClosingTheTelegramSheetMidSignInStopsItAtTheBackend() async throws {
        let api = FakeChatSourcesAPI()
        let model = TelegramChats(api: api)
        api.holdQR = true
        let asking = Task { await model.startQR() }
        while api.qrGate == nil { await Task.yield() }
        await model.abandonSignIn()                 // the sheet closed before the QR arrived
        XCTAssertEqual(api.telegramDisconnects, 0, "nothing to stop yet")
        api.qrGate?.resume()
        await asking.value
        XCTAssertEqual(api.telegramDisconnects, 1, "the late QR is stopped as it lands")
        api.telegramStatuses = [TelegramStatusAnswer(state: "password")]
        await model.refresh()
        await model.abandonSignIn()
        XCTAssertEqual(api.telegramDisconnects, 2, "a waiting password is a half sign-in too")
        api.telegramStatuses = [TelegramStatusAnswer(state: "connected")]
        await model.refresh()
        await model.abandonSignIn()
        XCTAssertEqual(api.telegramDisconnects, 2, "a connected session is never ended by closing the sheet")
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

    // MARK: One person across sources — a participant's ONE Contacts card, by id (the Messages rule)

    /// One pass over a ticked one-to-one chat and a ticked group, with Contacts faked (`ContactsTrap` is installed
    /// too, so nothing here can reach this Mac's Contacts).
    @MainActor
    private func cardPass(allowed: Bool, cards: [String: MessagesContactCard]) async throws -> [[String: Any]] {
        let friend = store.session(friendJid, name: "Bob Example")
        let group = store.session(groupJid, name: "Weekend crew")
        let alice = store.member(group, jid: "15550000003@s.whatsapp.net", name: "")
        store.message(friend, "C1", at: now.timeIntervalSinceReferenceDate - 10, text: "lunch?")
        store.message(group, "C2", at: now.timeIntervalSinceReferenceDate - 5, text: "hi all", member: alice)
        let api = FakeChatSourcesAPI()
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "whatsapp-test-\(UUID().uuidString)"))
        let watcher = WhatsAppWatcher(api: api, reader: reader(), defaults: defaults, folder: store.dir,
                                      makeWatch: { _, _ in nil },
                                      lookUpCards: { handles in cards.filter { handles.contains($0.key) } },
                                      lookUpContactsAllowed: { allowed })
        await watcher.loadList()
        for chat in watcher.chats { try await watcher.setTicked(chat, true) }
        for chat in watcher.chats { try await watcher.readHistory(chat) }
        return api.posts.compactMap { $0["conversation"] as? [String: Any] }
    }

    func testACardIsPostedForTheOneCardHoldingAHandleAndNeverTheNumber() async throws {
        let posted = try await cardPass(allowed: true, cards: [
            "+15550000002": MessagesContactCard(name: "Bob Example", thumbnail: nil, id: "CARD-BOB"),
            "+15550000003": MessagesContactCard(name: "Alice Example", thumbnail: nil, id: "CARD-ALICE")])
        let one = try XCTUnwrap(posted.first { ($0["group"] as? Bool) == false })
        XCTAssertEqual(one["contact"] as? String, "CARD-BOB")
        let group = try XCTUnwrap(posted.first { ($0["group"] as? Bool) == true })
        let member = try XCTUnwrap((group["members"] as? [[String: Any]])?.first)
        XCTAssertEqual(member["contact"] as? String, "CARD-ALICE")
        XCTAssertNil(group["contact"], "a group has no single card")
        let text = posted.map { String(describing: $0) }.joined()
        XCTAssertFalse(text.contains("5550000002") || text.contains("5550000003"), "a number never crosses")
    }

    func testSeveralCardsSayEmpty() async throws {
        let several = try await cardPass(allowed: true, cards: [
            "+15550000002": MessagesContactCard(name: "Bob Example", thumbnail: nil, id: nil)])
        XCTAssertEqual(several.first { ($0["group"] as? Bool) == false }?["contact"] as? String, "",
                       "looked up, none or several cards: the backend clears a stored card")
        let group = several.first { ($0["group"] as? Bool) == true }
        XCTAssertEqual((group?["members"] as? [[String: Any]])?.first?["contact"] as? String, "", "no card: cleared")
    }

    func testContactsUnreadSaysNothingAboutACard() async throws {
        let unread = try await cardPass(allowed: false, cards: [:])
        XCTAssertFalse(unread.isEmpty)
        XCTAssertTrue(unread.allSatisfy { $0["contact"] == nil }, "not looked up: nothing said, the stored card kept")
        XCTAssertTrue(unread.compactMap { $0["members"] as? [[String: Any]] }.joined().allSatisfy { $0["contact"] == nil })
    }
}
