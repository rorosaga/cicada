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

    // MARK: ROR-110 — the picker's Archived group and pictures

    func testArchivedChatsSitBelowTheRestAndCanStillBeTicked() async throws {
        store.exec("ALTER TABLE ZWACHATSESSION ADD COLUMN ZARCHIVED INTEGER")
        let old = store.session(friendJid, name: "Bob Example", last: 30)
        store.session(groupJid, name: "Weekend crew", last: 10)
        store.exec("UPDATE ZWACHATSESSION SET ZARCHIVED = 1 WHERE Z_PK = ?", [old])
        let w = try watcher(FakeChatSourcesAPI())
        await w.loadList()
        let sections = WhatsAppWatcher.sections(w.chats)
        XCTAssertEqual(sections.chats.map(\.jid), [groupJid], "newer activity never lifts an archived chat")
        XCTAssertEqual(sections.archived.map(\.jid), [friendJid])
        let archived = try XCTUnwrap(sections.archived.first)
        try await w.setTicked(archived, true)
        XCTAssertTrue(w.tickedIds.contains(archived.id))
    }

    func testAStoreWithNoArchivedColumnListsEveryChatAsUnarchived() async throws {
        store.session(friendJid, name: "Bob Example", last: 30)
        let w = try watcher(FakeChatSourcesAPI())
        await w.loadList()
        XCTAssertEqual(WhatsAppWatcher.sections(w.chats).chats.count, 1)
        XCTAssertTrue(WhatsAppWatcher.sections(w.chats).archived.isEmpty)
    }

    private func row(_ jid: String, _ path: String) {
        store.exec("INSERT INTO ZWAPROFILEPICTUREITEM (ZJID, ZPATH) VALUES (?, ?)", [jid, path])
    }

    func testAPictureIsTheOneItsOwnRowNamesForEveryKindOfChat() async throws {
        let linked = "200000000000002@lid"
        let stale = "15550000003@s.whatsapp.net"
        store.session(friendJid, name: "Bob Example", last: 40)
        store.session(groupJid, name: "Weekend crew", last: 30)
        store.session(linked, name: "Dan Example", last: 20)
        store.session(stale, name: "Carol Example", last: 10)
        for (jid, name) in [(friendJid, "a"), (groupJid, "b"), (linked, "c")] {
            row(jid, "Media/Profile/\(name)-1700000000.thumb")
            try writePicture("Media/Profile/\(name)-1700000000.thumb", side: 96)
        }
        row(stale, "Media/Profile/gone.jpg")
        let w = try watcher(FakeChatSourcesAPI())
        await w.loadList()
        for chat in w.chats where chat.jid != stale { XCTAssertNotNil(w.thumbnail(of: chat), chat.partnerName) }
        XCTAssertNil(w.thumbnail(of: try XCTUnwrap(w.chats.first { $0.jid == stale })), "a row with no file draws none")
    }

    func testAFileNoRowNamesIsNobodysPicture() async throws {
        store.session(friendJid, name: "Bob Example", last: 30)
        store.session(groupJid, name: "Weekend crew", last: 20)
        try writePicture("Media/Profile/15550000002.jpg", side: 96)
        try writePicture("Media/Profile/15550000002-1700000000.thumb", side: 96)
        try writePicture("Media/Profile/120363000000000000-1700000000.jpg", side: 96)
        let w = try watcher(FakeChatSourcesAPI())
        await w.loadList()
        for chat in w.chats { XCTAssertNil(w.thumbnail(of: chat), chat.partnerName) }
    }

    func testARowNamingOneExtensionFindsItsSiblingFile() async throws {
        store.session(friendJid, name: "Bob Example", last: 30)
        store.exec("INSERT INTO ZWAPROFILEPICTUREITEM (ZJID, ZPATH) VALUES (?, ?)", [friendJid, "Media/Profile/x-1.jpg"])
        try writePicture("Media/Profile/x-1.thumb", side: 96)
        let w = try watcher(FakeChatSourcesAPI())
        await w.loadList()
        XCTAssertNotNil(w.thumbnail(of: try XCTUnwrap(w.chats.first)))
    }

    func testAGroupsFileIsNeverItsCreatorsPicture() async throws {
        let legacyGroup = "15550000002-1600000000@g.us"
        store.session(friendJid, name: "Bob Example", last: 30)
        row(legacyGroup, "Media/Profile/15550000002-1600000000.thumb")
        try writePicture("Media/Profile/15550000002-1600000000.thumb", side: 96)
        let unlisted = try watcher(FakeChatSourcesAPI())
        await unlisted.loadList()
        XCTAssertEqual(unlisted.chats.map(\.jid), [friendJid], "the group is not among the listed chats")
        XCTAssertNil(unlisted.thumbnail(of: try XCTUnwrap(unlisted.chats.first)), "the creator's chat never wears it")
        store.session(legacyGroup, name: "Weekend crew", last: 20)
        let listed = try watcher(FakeChatSourcesAPI())
        await listed.loadList()
        XCTAssertNil(listed.thumbnail(of: try XCTUnwrap(listed.chats.first { $0.jid == friendJid })))
        XCTAssertNotNil(listed.thumbnail(of: try XCTUnwrap(listed.chats.first { $0.jid == legacyGroup })))
    }

    func testTheChatWithYourselfWearsYourOwnPhoto() async throws {
        try writeOwnAccount(ownJid)
        store.session(ownJid, name: "You", last: 30)
        try writePicture("Media/Profile/Photo.jpg", side: 96)
        let w = try watcher(FakeChatSourcesAPI())
        await w.loadList()
        XCTAssertNotNil(w.thumbnail(of: try XCTUnwrap(w.chats.first)))
    }

    /// The rail: before a tick the picture and the flag stay in this app's memory, and neither needs a message row.
    func testAnUntickedChatsPictureNeverLeavesTheAppOrReachesADisk() async throws {
        store.exec("ALTER TABLE ZWACHATSESSION ADD COLUMN ZARCHIVED INTEGER")
        store.session(friendJid, name: "Bob Example", last: 30)
        store.exec("UPDATE ZWACHATSESSION SET ZARCHIVED = 1")
        store.exec("DROP TABLE ZWAMESSAGE")
        row(friendJid, "Media/Profile/15550000002-1700000000.thumb")
        try writePicture("Media/Profile/15550000002-1700000000.thumb", side: 96)
        let scratch = store.dir.appendingPathComponent("reader-scratch", isDirectory: true)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
        let before = try XCTUnwrap(FileManager.default.subpathsOfDirectory(atPath: store.dir.path).sorted() as [String]?)
        let api = FakeChatSourcesAPI()
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "chats-ux-v2-\(UUID().uuidString)"))
        let w = WhatsAppWatcher(api: api, reader: WhatsAppReader(store: store.url, scratchRoot: scratch),
                                defaults: defaults, folder: store.dir, makeWatch: { _, _ in nil },
                                lookUpCards: { _ in [:] })
        await w.loadList()
        let chat = try XCTUnwrap(w.chats.first)
        XCTAssertTrue(chat.archived)
        XCTAssertNotNil(w.thumbnail(of: chat))
        XCTAssertTrue(api.photoPosts.isEmpty, "nothing posted before a tick")
        XCTAssertEqual(try FileManager.default.subpathsOfDirectory(atPath: store.dir.path).sorted(), before,
                       "no file written, the reader's own scratch included")
    }

    func testAPhoneChatWithNoPictureOfItsOwnWearsItsLids() async throws {
        let bare = "15550000003@s.whatsapp.net", owned = "15550000004@s.whatsapp.net"
        let unbridged = "15550000005@s.whatsapp.net", torn = "15550000006@s.whatsapp.net"
        for (i, jid) in [friendJid, bare, owned, unbridged, torn, groupJid].enumerated() {
            store.session(jid, name: "Chat \(i)", last: Double(100 - i))
        }
        store.addressBook([(friendJid, "200000000000002@lid"), ("15550000003", "200000000000003@lid"),
                           (owned, "200000000000004@lid"), (groupJid, "200000000000007@lid"),
                           (unbridged, "200000000000005"),
                           (torn, "200000000000008@lid"), (torn, "200000000000009@lid")])
        for lid in ["2", "3", "4", "5", "7", "8", "9"] {
            row("20000000000000\(lid)@lid", "Media/Profile/20000000000000\(lid)-1700000000.thumb")
            try writePicture("Media/Profile/20000000000000\(lid)-1700000000.thumb", side: 64)
        }
        row(owned, "Media/Profile/15550000004-1700000000.thumb")
        try writePicture("Media/Profile/15550000004-1700000000.thumb", side: 96)
        let scratch = store.dir.appendingPathComponent("reader-scratch", isDirectory: true)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
        let api = FakeChatSourcesAPI()
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "chats-ux-v2-\(UUID().uuidString)"))
        let w = WhatsAppWatcher(api: api, reader: WhatsAppReader(store: store.url, scratchRoot: scratch),
                                defaults: defaults, folder: store.dir, makeWatch: { _, _ in nil },
                                lookUpCards: { _ in [:] })
        await w.loadList()
        func chat(_ jid: String) throws -> WhatsAppChat { try XCTUnwrap(w.chats.first { $0.jid == jid }) }
        XCTAssertNotNil(w.thumbnail(of: try chat(friendJid)), "ZWHATSAPPID with its suffix")
        XCTAssertNotNil(w.thumbnail(of: try chat(bare)), "ZWHATSAPPID without its suffix")
        let own = try XCTUnwrap(w.thumbnail(of: try chat(owned)))
        let source = try XCTUnwrap(CGImageSourceCreateWithData(own as CFData, nil))
        let props = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertEqual(props[kCGImagePropertyPixelWidth] as? Int, 96, "its own picture comes first")
        XCTAssertNil(w.thumbnail(of: try chat(unbridged)), "a ZLID that is no @lid id bridges nothing")
        XCTAssertNil(w.thumbnail(of: try chat(torn)), "a number with two ids wears neither")
        XCTAssertNil(w.thumbnail(of: try chat(groupJid)), "a group never bridges")
        XCTAssertTrue(api.photoPosts.isEmpty, "nothing posted before a tick")
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: scratch.path), [], "the copy is gone")
        // Read once per list load: a tick's post finds it with the file gone.
        try FileManager.default.removeItem(at: store.dir.appendingPathComponent("ContactsV2.sqlite"))
        try await w.setTicked(try chat(friendJid), true)
        XCTAssertNotNil(try XCTUnwrap(api.photoPosts.last?.first).photoB64)
    }

    func testNoAddressBookTableOrColumnMeansNoBridgeAndNoError() async throws {
        store.session(friendJid, name: "Bob Example", last: 30)
        row("200000000000002@lid", "Media/Profile/200000000000002-1700000000.thumb")
        try writePicture("Media/Profile/200000000000002-1700000000.thumb", side: 64)
        let file = store.dir.appendingPathComponent("ContactsV2.sqlite")
        func check(_ note: String) async throws {
            let w = try watcher(FakeChatSourcesAPI())
            await w.loadList()
            XCTAssertNil(w.thumbnail(of: try XCTUnwrap(w.chats.first)), note)
            if case .failed = w.status { XCTFail(note) }
            if case .needsAccess = w.status { XCTFail(note) }
        }
        try await check("no file")
        store.addressBook(schema: "CREATE TABLE OTHER (ZWHATSAPPID VARCHAR, ZLID VARCHAR);")
        try await check("no table")
        try FileManager.default.removeItem(at: file)
        store.addressBook(schema: "CREATE TABLE ZWAADDRESSBOOKCONTACT (Z_PK INTEGER PRIMARY KEY, ZWHATSAPPID VARCHAR);")
        try await check("no column")
        try Data("not a database".utf8).write(to: file)
        try await check("unreadable")
    }

    func testAMissingPermissionReadsAsNeedsAccessNotAnEmptyPicker() async throws {
        store.session(friendJid, name: "Bob Example", last: 30)
        try FileManager.default.setAttributes([.posixPermissions: 0], ofItemAtPath: store.url.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: store.url.path) }
        let w = try watcher(FakeChatSourcesAPI())
        await w.loadList()
        guard case .needsAccess = w.status else { return XCTFail("\(w.status)") }
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
