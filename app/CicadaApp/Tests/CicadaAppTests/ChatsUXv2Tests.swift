import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import CicadaApp

/// chats-ux-v2 (owner 2026-10-29) — the chat-specific fixes, against the synthetic WhatsApp store and a fake backend:
/// the person's own chat ("You") is found and posted as their notes, never as a correspondent with their card; a
/// refusal says what failed and what to do; each chat's picture comes from WhatsApp's own data on this Mac and a ticked
/// one-to-one chat's is posted to the chat-photo store; the pickers search by name or number, most recent first; and
/// the Telegram QR step waits on the status's version instead of reading it once a second.
@MainActor
final class ChatsUXv2Tests: XCTestCase {
    var store: SyntheticWhatsAppStore!
    let ownJid = "15550000001@s.whatsapp.net"          // placeholder JIDs — never real numbers
    let friendJid = "15550000002@s.whatsapp.net"
    let groupJid = "120363000000000000@g.us"

    override func setUpWithError() throws {
        ContactsTrap.install()
        store = try SyntheticWhatsAppStore()
    }
    override func tearDown() { store.close() }

    /// The shape a real install keeps (structure check 2026-10-29, names only): the phone JID under `OwnJabberID` and
    /// `LastOwnJabberID`, the linked-identity id under `lid`/`lidd`, other keys that are not JIDs, and Data values.
    private func writeOwnAccount(_ jid: String, lid: String = "200000000000001@lid") throws {
        let prefs = store.dir.appendingPathComponent("Library/Preferences", isDirectory: true)
        try FileManager.default.createDirectory(at: prefs, withIntermediateDirectories: true)
        let values: [String: Any] = ["OwnJabberID": jid, "LastOwnJabberID": jid, "lid": lid, "lidd": lid,
                                     "llid": "not-a-jid", "lids": "1", "OwnBlob": Data([1, 2, 3]), "Other": "x"]
        let data = try PropertyListSerialization.data(fromPropertyList: values, format: .binary, options: 0)
        try data.write(to: prefs.appendingPathComponent("group.net.whatsapp.WhatsApp.shared.plist"))
    }

    private func writePicture(_ relative: String, side: Int = 640) throws {
        let url = store.dir.appendingPathComponent(relative)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let ctx = try XCTUnwrap(CGContext(data: nil, width: side, height: side, bitsPerComponent: 8, bytesPerRow: 0,
                                          space: CGColorSpaceCreateDeviceRGB(),
                                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        ctx.setFillColor(CGColor(red: 0.2, green: 0.4, blue: 0.6, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: side, height: side))
        let image = try XCTUnwrap(ctx.makeImage())
        let dest = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, UTType.jpeg.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(dest, image, nil)
        XCTAssertTrue(CGImageDestinationFinalize(dest))
    }

    private func watcher(_ api: FakeChatSourcesAPI) throws -> WhatsAppWatcher {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "chats-ux-v2-\(UUID().uuidString)"))
        return WhatsAppWatcher(api: api, reader: WhatsAppReader(store: store.url), defaults: defaults, folder: store.dir,
                               makeWatch: { _, _ in nil }, lookUpCards: { _ in [:] })
    }

    func testTheChatWithYourselfIsPostedAsYourNotesNeverAsACorrespondent() async throws {
        try writeOwnAccount(ownJid)
        let me = store.session(ownJid, name: "You", last: 20)
        store.session(friendJid, name: "Bob Example", last: 10)
        store.message(me, "S1", at: 700_000_000, text: "idea for alpha-project", fromMe: true)
        let api = FakeChatSourcesAPI()
        let w = try watcher(api)
        await w.loadList()
        let mine = try XCTUnwrap(w.chats.first { $0.jid == ownJid })
        XCTAssertTrue(mine.isSelf)
        XCTAssertFalse(try XCTUnwrap(w.chats.first { $0.jid == friendJid }).isSelf)
        XCTAssertEqual(w.name(of: mine), Copy.Chats.selfChat)
        try await w.setTicked(mine, true)
        try await w.readHistory(mine)
        let conversation = try XCTUnwrap(api.posts.last?["conversation"] as? [String: Any])
        XCTAssertEqual(conversation["selfChat"] as? Bool, true)
        XCTAssertNil(conversation["contact"], "the person's own card is never a correspondent's")
        XCTAssertFalse(String(describing: api.posts).contains("5550000001"), "the number never crosses")
    }

    /// On a real install the self-chat's session carries the person's LID (`<digits>@lid`), matched by `lid`/`lidd` —
    /// neither phone-JID key — and status, channel and broadcast shapes never list.
    func testTheChatWithYourselfIsFoundByTheLinkedIdentityAndStatusShapesNeverList() throws {
        try writeOwnAccount(ownJid, lid: "200000000000001@lid")
        store.session("200000000000001@lid", name: "You", last: 30)
        store.session("200000000000002@lid", name: "Erin Example", last: 20)
        store.session(friendJid, name: "Bob Example", last: 10)
        for jid in ["200000000000003@lid.status", "0@status", "120363999999999999@newsletter", "1234@broadcast"] {
            store.session(jid, name: "", last: 5)
        }
        let chats = try WhatsAppReader(store: store.url).chats()
        XCTAssertEqual(chats.map(\.partnerName), ["You", "Erin Example", "Bob Example"])
        XCTAssertEqual(chats.map(\.isSelf), [true, false, false])
        XCTAssertEqual(WhatsAppReader(store: store.url).ownAccounts(), ["15550000001", "200000000000001"])
    }

    /// Messages' note to self: the chat's handle is one of the person's own (the handle Messages addressed from, or an
    /// account login on this Mac) — posted as their notes, never with a card.
    func testAMessagesNoteToSelfIsFoundAndPostedAsYourNotes() throws {
        let db = try SyntheticChatDB()
        defer { db.close() }
        let mine = db.chat("+15550000001")
        let friend = db.chat("+15550000002")
        db.exec("UPDATE chat SET last_addressed_handle = '+15550000001', account_login = 'P:+15550000001'")
        db.message(mine, minute: 1, fromMe: true, text: "idea for alpha-project")
        db.message(friend, minute: 2, fromMe: false, text: "hello")
        let reader = MessagesReader(database: db.url)
        let listed = try reader.conversations()
        XCTAssertEqual(listed.filter(\.isSelf).map(\.chatRowId), [mine])
        let own = try XCTUnwrap(listed.first(where: \.isSelf))
        let pass = try reader.read(own, name: Copy.Chats.selfChat, contact: "PLACEHOLDER-ME-CARD",
                                   since: MessagesCursor())
        let conversation = try XCTUnwrap((JSONSerialization.jsonObject(with: pass.json) as? [String: Any])?["conversation"]
                                         as? [String: Any])
        XCTAssertEqual(conversation["selfChat"] as? Bool, true)
        XCTAssertNil(conversation["contact"])
    }

    func testNoOwnAccountOnRecordTakesNoChatForYours() throws {
        store.session(ownJid, name: "You", last: 20)
        XCTAssertFalse(try XCTUnwrap(WhatsAppReader(store: store.url).chats().first).isSelf)
    }

    func testARefusalSaysWhatFailedAndWhatToDo() {
        let refused = APIError.httpError(422, #"{"detail":[{"type":"string_too_long"}]}"#)
        let line = WhatsAppWatcher.failureMessage(refused)
        XCTAssertTrue(line.contains("422") && line.contains("Refresh"), line)
        XCTAssertEqual(WhatsAppWatcher.failureMessage(APIError.httpError(409, #"{"detail":"Tick it first."}"#)),
                       "Tick it first.", "the backend's own sentence wins")
        XCTAssertFalse(Copy.Chats.syncFailed.hasPrefix("Couldn't"), "never a bare couldn't")
        XCTAssertEqual(TelegramChats.message(refused), line, "one reading for both sources")
    }

    func testEachChatsPictureComesFromWhatsAppsOwnDataAndATickedOneIsPosted() async throws {
        store.session(friendJid, name: "Bob Example", last: 10)
        store.session(groupJid, name: "Weekend crew", last: 5)
        store.exec("INSERT INTO ZWAPROFILEPICTUREITEM (ZJID, ZPATH) VALUES (?, ?)",
                   [friendJid, "Media/Profile/placeholder-friend.thumb"])
        store.exec("INSERT INTO ZWAPROFILEPICTUREITEM (ZJID, ZPATH) VALUES (?, ?)",
                   [groupJid, "../../outside.thumb"])
        try writePicture("Media/Profile/placeholder-friend.thumb")
        let api = FakeChatSourcesAPI()
        let w = try watcher(api)
        await w.loadList()
        let friend = try XCTUnwrap(w.chats.first { $0.jid == friendJid })
        let picture = try XCTUnwrap(w.thumbnail(of: friend))
        let source = try XCTUnwrap(CGImageSourceCreateWithData(picture as CFData, nil))
        let props = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertLessThanOrEqual(props[kCGImagePropertyPixelWidth] as? Int ?? 999, 128, "made small on this Mac")
        XCTAssertNil(w.thumbnail(of: try XCTUnwrap(w.chats.first { $0.jid == groupJid })), "never outside the container")
        try await w.setTicked(friend, true)
        let posted = try XCTUnwrap(api.photoPosts.last)
        XCTAssertEqual(posted.map(\.conversation), [friend.id])
        XCTAssertNotNil(posted.first?.photoB64)
        _ = try await w.syncNow()
        XCTAssertEqual(api.photoPosts.count, 1, "an unchanged picture is never posted again")
    }

    func testThePickerSearchesByNameOrNumberAndKeepsTheMostRecentFirst() async throws {
        store.session("15550000003@s.whatsapp.net", name: "Álvaro Example", last: 30)
        store.session(friendJid, name: "Bob Example", last: 20)
        store.session(groupJid, name: "Weekend crew", last: 10)
        let w = try watcher(FakeChatSourcesAPI())
        await w.loadList()
        XCTAssertEqual(w.filtered("").map(\.partnerName), ["Álvaro Example", "Bob Example", "Weekend crew"])
        XCTAssertEqual(w.filtered("alvaro").map(\.partnerName), ["Álvaro Example"], "accents and case ignored")
        XCTAssertEqual(w.filtered("example").map(\.partnerName), ["Álvaro Example", "Bob Example"])
        XCTAssertEqual(w.filtered("0000002").map(\.partnerName), ["Bob Example"], "a number fragment")
        XCTAssertEqual(w.filtered("+1 555 000 0002").map(\.partnerName), ["Bob Example"])
        XCTAssertEqual(w.filtered("55").map(\.partnerName), [], "two digits match nothing by number")
        let rows = [TelegramChatRow(id: "a", name: "Carol Example"), TelegramChatRow(id: "b", name: "Dave Example")]
        XCTAssertEqual(ChatSearch.filter(rows, query: "dave", name: \.name).map(\.id), ["b"])
    }

    /// The picker's open cost (the list read, Contacts stubbed), 300 chats, with and without WhatsApp pictures to read.
    func testThePickerOpenCostWithPictures() async throws {
        store.exec("BEGIN")
        for i in 0..<300 {
            let jid = "1555\(String(format: "%07d", i))@s.whatsapp.net"
            store.session(jid, name: "Person \(i)", last: Double(i))
            store.exec("INSERT INTO ZWAPROFILEPICTUREITEM (ZJID, ZPATH) VALUES (?, ?)", [jid, "Media/Profile/p\(i).thumb"])
        }
        store.exec("COMMIT")
        func p95() async throws -> Double {
            var took: [Double] = []
            for _ in 0..<10 {
                let w = try watcher(FakeChatSourcesAPI())
                let start = ContinuousClock.now
                await w.loadList()
                took.append(WhatsAppWatcher.seconds(ContinuousClock.now - start))
            }
            return took.sorted()[8] * 1000
        }
        let without = try await p95()
        for i in 0..<300 { try writePicture("Media/Profile/p\(i).thumb", side: 96) }
        let with = try await p95()
        print("whatsapp picker open p95: \(String(format: "%.1f", without)) ms without pictures, "
              + "\(String(format: "%.1f", with)) ms reading 300 pictures")
        XCTAssertLessThan(with, 1000)
    }

    func testTheQRStepWaitsOnTheStatusVersionInsteadOfPolling() async throws {
        let api = FakeChatSourcesAPI()
        api.qrVersion = "aaaaaaaaaaaa"
        let model = TelegramChats(api: api)
        await model.startQR()
        var done = TelegramStatusAnswer(state: "connected")
        done.version = "bbbbbbbbbbbb"
        api.telegramStatuses = [done]
        let started = ContinuousClock.now
        await model.followQR(every: .seconds(30))     // a once-a-second poll would sleep first; the long-poll does not
        XCTAssertTrue(model.connected)
        XCTAssertEqual(api.statusWaits, ["aaaaaaaaaaaa"], "asked once, with the version it held")
        XCTAssertLessThan(ContinuousClock.now - started, .seconds(1))
    }
}
