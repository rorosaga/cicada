import AppKit
import XCTest
@testable import CicadaApp

/// Chat images (owner 2026-11-04: "I don't see images appearing when I open the chat inside the app") — against
/// synthetic stores only (placeholder JIDs, handles and files): a turn's attachment is the file the chat app holds,
/// found by the turn's second and the stored name and place; a file not on this Mac is the placeholder; nothing of a
/// chat that is not ticked is read or kept; a store path that leaves the app's folder is no file; thumbnails live
/// outside every bank and go on untick; Telegram is asked of the backend with the turn's own time.
final class ChatMediaTests: XCTestCase {
    private let chat = String(repeating: "ab", count: 12)

    private func doc(origin: String, chat: String, turns: [(ts: String, attachments: [EpisodeAttachment])]) -> EpisodeText {
        var text = ""
        var built: [EpisodeTurn] = []
        for (i, turn) in turns.enumerated() {
            let line = "speaker:bob-example: [image: x]\n"
            let start = text.unicodeScalars.count
            text += line
            built.append(EpisodeTurn(index: i, start: start, contentStart: start + 20, end: text.unicodeScalars.count,
                                     role: "speaker", marker: "speaker:bob-example", ts: turn.ts,
                                     extras: EpisodeTurnExtras(attachments: turn.attachments)))
        }
        return EpisodeText(episode: "ep_2026-11-04_001", text: text, origin: origin,
                           conversationId: "\(origin):\(chat):k1", turns: built)
    }

    // MARK: Which chat, which files

    func testASittingNamesItsChatOnlyForAChatSource() {
        let whatsApp = doc(origin: "whatsapp", chat: chat, turns: [])
        XCTAssertEqual(ChatMedia.source(whatsApp), ChatMediaSource(channel: .whatsApp, chat: chat))
        XCTAssertEqual(ChatMedia.source(doc(origin: "imessage", chat: chat, turns: []))?.channel, .messages)
        XCTAssertEqual(ChatMedia.source(doc(origin: "telegram-chats", chat: chat, turns: []))?.channel, .telegram)
        XCTAssertNil(ChatMedia.source(doc(origin: "claude-code", chat: chat, turns: [])))
        XCTAssertNil(ChatMedia.source(doc(origin: "whatsapp", chat: "not/hex", turns: [])), "a chat id never reshapes a path")
    }

    func testEachAttachmentKnowsItsPlaceAmongThatSecondsSameFiles() {
        let photo = EpisodeAttachment(kind: "image", name: "unnamed")
        let d = doc(origin: "telegram-chats", chat: chat, turns: [
            ("2026-11-04T10:00:00+00:00", [photo]), ("2026-11-04T10:00:00+00:00", [photo]),
            ("2026-11-04T10:00:00+00:00", [EpisodeAttachment(kind: "audio", name: "voice.ogg")]),
            ("2026-11-04T10:05:00+00:00", [photo, photo]),
        ])
        let files = ChatMedia.files(d)
        XCTAssertEqual(files[0]?.map(\.n), [0])
        XCTAssertEqual(files[1]?.map(\.n), [1], "an album's second photo, the same second")
        XCTAssertEqual(files[2]?.map(\.n), [0])
        XCTAssertEqual(files[3]?.map(\.n), [0, 1])
        XCTAssertEqual(files[3]?.first?.source?.channel, .telegram)
        XCTAssertNotEqual(files[0]?.first?.cacheKey, files[1]?.first?.cacheKey)
    }

    func testNamesAndKindsAreTheBackendsOwn() {
        XCTAssertEqual(ChatMedia.normalizedName("Media/x/[draft]  plan.pdf"), "(draft) plan.pdf")
        XCTAssertEqual(ChatMedia.normalizedName(""), "unnamed")
        XCTAssertEqual(ChatMedia.normalizedName(String(repeating: "a", count: 200)).count, 120)
        XCTAssertEqual(ChatMedia.kind(mime: "video/mp4", name: "x"), "video")
        XCTAssertEqual(ChatMedia.kind(mime: nil, name: "IMG_1.HEIC"), "image")
        XCTAssertEqual(ChatMedia.kind(mime: nil, name: "note.opus"), "audio")
        XCTAssertEqual(ChatMedia.kind(mime: nil, name: "plan.pdf"), "file")
        XCTAssertEqual(MessagesReader.attachmentKind(mime: nil, uti: "public.heic"), "image")
        XCTAssertEqual(ChatMedia.length(7), "0:07")
        XCTAssertEqual(ChatMedia.length(3723), "1:02:03")
    }

    func testPickTakesTheNthOfThatSecondThenTheKindThenAUniqueName() {
        let at = Date(timeIntervalSince1970: 1_793_000_000)
        func candidate(_ order: Int64, _ offset: TimeInterval, _ name: String, _ kind: String = "image") -> ChatMediaCandidate {
            ChatMediaCandidate(order: order, date: at.addingTimeInterval(offset), name: name, kind: kind)
        }
        let list = [candidate(1, 0.4, "a.jpg"), candidate(2, 0.6, "a.jpg"), candidate(3, 0.2, "b.jpg"),
                    candidate(4, 600, "far.jpg"), candidate(5, 0.1, "voice.opus", "audio")]
        let stamp = ISO8601DateFormatter().string(from: at)
        func file(_ name: String, _ n: Int = 0, kind: String = "image", at: String? = stamp) -> ChatFile {
            ChatFile(source: nil, kind: kind, name: name, size: nil, at: at, n: n)
        }
        XCTAssertEqual(ChatMedia.pick(list, file: file("a.jpg"))?.order, 1)
        XCTAssertEqual(ChatMedia.pick(list, file: file("a.jpg", 1))?.order, 2)
        XCTAssertNil(ChatMedia.pick(list, file: file("a.jpg", 2)))
        XCTAssertEqual(ChatMedia.pick(list, file: file("scrubbed name"))?.order, 3, "the kind when the name moved")
        XCTAssertEqual(ChatMedia.pick(list, file: file("far.jpg"))?.order, 4, "a name only one file carries")
        XCTAssertEqual(ChatMedia.pick(list, file: file("far.jpg", at: nil))?.order, 4)
        XCTAssertNil(ChatMedia.pick(list, file: file("unnamed", at: nil)), "a generic name needs its time")
        XCTAssertEqual(ChatMedia.pick(list, file: file("voice.opus", kind: "audio"))?.order, 5)
    }

    // MARK: The stores

    private func png(_ url: URL, width: Int = 64, height: Int = 48) throws {
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height, bitsPerSample: 8,
                                   samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                   bytesPerRow: 0, bitsPerPixel: 0)!
        for x in 0..<width { for y in 0..<height { rep.setColor(.systemTeal, atX: x, y: y) } }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try rep.representation(using: .png, properties: [:])!.write(to: url)
    }

    func testWhatsAppMediaIsFoundInsideItsContainerOnly() throws {
        let store = try SyntheticWhatsAppStore()
        defer { store.close() }
        store.exec("ALTER TABLE ZWAMEDIAITEM ADD COLUMN ZMOVIEDURATION INTEGER")
        let session = store.session("10000000001@s.whatsapp.net", name: "Bob Example")
        let pk = store.message(session, "S1", at: 800_000_000, text: nil, type: 1,
                               media: (title: nil, path: "Media/10000000001@s.whatsapp.net/a/b/photo-1.jpg", size: 10, metadata: nil))
        store.message(session, "S2", at: 800_000_060, text: nil, type: 2,
                      media: (title: nil, path: "Media/10000000001@s.whatsapp.net/a/b/clip-1.mp4", size: 10, metadata: nil))
        store.exec("UPDATE ZWAMEDIAITEM SET ZMOVIEDURATION = 42 WHERE ZMESSAGE = ?", [pk + 1])
        store.message(session, "S3", at: 800_000_120, text: nil, type: 1,
                      media: (title: nil, path: "Media/../../outside.jpg", size: 10, metadata: nil))
        store.message(session, "S4", at: 800_000_180, text: nil, type: 1,
                      media: (title: "not downloaded", path: nil, size: 10, metadata: nil))
        store.message(session, "S5", at: 800_000_240, text: "a link", type: 7,
                      media: (title: "preview", path: "Media/link.jpg", size: 10, metadata: nil))
        try png(store.dir.appendingPathComponent("Message/Media/10000000001@s.whatsapp.net/a/b/photo-1.jpg"))
        let reader = WhatsAppReader(store: store.url, scratchRoot: store.dir)
        let found = try reader.media(XCTUnwrap(reader.chats().first))
        XCTAssertEqual(found.map(\.name), ["photo-1.jpg", "clip-1.mp4", "outside.jpg", "not downloaded"],
                       "a link preview is no attachment")
        XCTAssertEqual(found[0].kind, "image")
        XCTAssertNotNil(found[0].file, "the file WhatsApp keeps under Message/")
        XCTAssertEqual(found[1].kind, "video")
        XCTAssertEqual(found[1].length, 42)
        XCTAssertNil(found[1].file, "not on this Mac")
        XCTAssertNil(found[2].file, "a path that leaves the container is no file")
        XCTAssertNil(found[3].file)
        XCTAssertEqual(found[0].date, Date(timeIntervalSinceReferenceDate: 800_000_000))
    }

    func testAMessagesAttachmentIsTheFileBesideChatDB() throws {
        let db = try SyntheticChatDB()
        defer { db.close() }
        let c = db.chat("+15550000001")
        db.message(c, minute: 1, fromMe: false, text: nil, attachment: "IMG_0001.HEIC")
        db.message(c, minute: 2, fromMe: true, text: "no file here", attachment: "IMG_0002.PNG")
        try png(db.dir.appendingPathComponent("Attachments/CANARY-path/IMG_0001.HEIC"))
        let reader = MessagesReader(database: db.url)
        let id = MessagesReader.conversationId(chatGuid: "iMessage;-;+15550000001")
        let found = try reader.media(conversation: id)
        XCTAssertEqual(found.map(\.name), ["IMG_0001.HEIC", "IMG_0002.PNG"])
        XCTAssertEqual(found.map(\.kind), ["image", "image"])
        XCTAssertNotNil(found[0].file)
        XCTAssertNil(found[1].file, "an attachment kept only in iCloud has no file here")
        XCTAssertNil(reader.attachmentFile("~/Library/Messages/Attachments/../chat.db", root: reader.attachmentsFolder))
        XCTAssertNil(reader.attachmentFile("/etc/hosts", root: reader.attachmentsFolder))
        XCTAssertTrue(try reader.media(conversation: String(repeating: "0", count: 24)).isEmpty)
    }

    // MARK: The store end to end

    @MainActor
    func testATickedChatsPhotoIsDrawnCachedOutsideTheBankAndGoneOnUntick() async throws {
        let store = try SyntheticWhatsAppStore()
        defer { store.close() }
        let jid = "10000000002@s.whatsapp.net"
        let session = store.session(jid, name: "Bob Example")
        store.message(session, "S1", at: 800_000_000.4, text: nil, type: 1,
                      media: (title: nil, path: "Media/x/photo-2.jpg", size: 10, metadata: nil))
        store.message(session, "S2", at: 800_000_100, text: nil, type: 1,
                      media: (title: nil, path: "Media/x/gone.jpg", size: 10, metadata: nil))
        try png(store.dir.appendingPathComponent("Message/Media/x/photo-2.jpg"), width: 80, height: 60)
        let cache = store.dir.appendingPathComponent("cicada-home/chat-media")
        let media = ChatMediaStore(whatsAppStore: store.url, messagesDatabase: store.url, cacheRoot: cache,
                                   telegram: { _, _, _ in nil })
        let source = ChatMediaSource(channel: .whatsApp, chat: WhatsAppReader.chatId(jid: jid))
        let at = ISO8601DateFormatter().string(from: Date(timeIntervalSinceReferenceDate: 800_000_000))
        let photo = ChatFile(source: source, kind: "image", name: "photo-2.jpg", size: 10, at: at, n: 0)

        let unticked = await media.shown(photo, ticked: false)
        XCTAssertFalse(unticked.onMac)
        XCTAssertNil(unticked.thumbnail, "a chat that is not ticked is never read")
        XCTAssertFalse(FileManager.default.fileExists(atPath: cache.path))

        let shown = await media.shown(photo, ticked: true)
        XCTAssertTrue(shown.onMac)
        guard case .file(let url)? = shown.large else { return XCTFail("a photo on this Mac opens large") }
        XCTAssertEqual(url.lastPathComponent, "photo-2.jpg")
        let kept = try XCTUnwrap(ChatMediaCache.file(source, key: photo.cacheKey, root: cache))
        XCTAssertNotNil(shown.thumbnail, "Quick Look's own thumbnail of the file")
        XCTAssertTrue(FileManager.default.fileExists(atPath: kept.path), "the thumbnail is kept outside every bank")
        let mode = try FileManager.default.attributesOfItem(atPath: kept.path)[.posixPermissions] as? Int
        XCTAssertEqual(mode, 0o600)

        let missing = await media.shown(ChatFile(source: source, kind: "image", name: "gone.jpg", size: 10,
                                                  at: nil, n: 0), ticked: true)
        XCTAssertFalse(missing.onMac, "a file not on this Mac is the placeholder with its name")
        XCTAssertNil(missing.large)

        media.forget(source)
        XCTAssertFalse(FileManager.default.fileExists(atPath: kept.deletingLastPathComponent().path), "gone on untick")
    }

    @MainActor
    func testTelegramIsAskedOfTheBackendWithTheTurnsOwnTime() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("ChatMediaTG-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 8, pixelsHigh: 8, bitsPerSample: 8,
                                   samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                   bytesPerRow: 0, bitsPerPixel: 0)!
        let preview = rep.representation(using: .png, properties: [:])!
        let asked = AskLog()
        let media = ChatMediaStore(whatsAppStore: dir, messagesDatabase: dir, cacheRoot: dir, telegram: { chat, file, full in
            await asked.add("\(chat)|\(file.at ?? "")|\(file.n)|\(full)")
            if full { return preview }
            let body: [String: Any] = ["found": true, "kind": "image", "preview": preview.base64EncodedString()]
            return try JSONSerialization.data(withJSONObject: body)
        })
        let source = ChatMediaSource(channel: .telegram, chat: chat)
        let photo = ChatFile(source: source, kind: "image", name: "unnamed", size: nil,
                             at: "2026-11-04T10:00:00+00:00", n: 1)
        let shown = await media.shown(photo, ticked: false)
        XCTAssertTrue(shown.onMac, "Telegram's tick is the backend's to check")
        XCTAssertNotNil(shown.thumbnail)
        XCTAssertEqual(shown.large, .telegram)
        let url = await media.largeFile(photo, .telegram)
        XCTAssertEqual(try url.map { try Data(contentsOf: $0) }, preview)
        let log = await asked.lines
        XCTAssertEqual(log, ["\(chat)|2026-11-04T10:00:00+00:00|1|false", "\(chat)|2026-11-04T10:00:00+00:00|1|true"])
        _ = await media.largeFile(photo, .telegram)
        let again = await asked.lines
        XCTAssertEqual(again.count, 2, "the large photo is kept beside the thumbnails until untick")
    }

    func testTheCacheNeverLeavesItsFolder() {
        let root = URL(fileURLWithPath: "/tmp/cicada-chat-media-test")
        XCTAssertNil(ChatMediaCache.folder(ChatMediaSource(channel: .whatsApp, chat: "../../x"), root: root))
        XCTAssertNil(ChatMediaCache.file(ChatMediaSource(channel: .whatsApp, chat: chat), key: "../x", root: root))
        XCTAssertEqual(ChatMediaCache.folder(ChatMediaSource(channel: .messages, chat: chat), root: root)?.path,
                       "/tmp/cicada-chat-media-test/imessage/\(chat)")
    }

    func testAChatUntickedElsewhereLosesItsThumbnailsWhenTheTicksAreRead() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("ChatMediaKeep-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let kept = ChatMediaSource(channel: .whatsApp, chat: chat)
        let gone = ChatMediaSource(channel: .whatsApp, chat: String(repeating: "cd", count: 12))
        let other = ChatMediaSource(channel: .messages, chat: String(repeating: "cd", count: 12))
        for source in [kept, gone, other] { XCTAssertNotNil(ChatMediaCache.write(Data([1]), source, key: "abc", root: root)) }
        XCTAssertEqual(ChatMediaCache.keepOnly(.whatsApp, ticked: [chat], root: root), 1)
        XCTAssertNotNil(ChatMediaCache.read(kept, key: "abc", root: root))
        XCTAssertNil(ChatMediaCache.read(gone, key: "abc", root: root))
        XCTAssertNotNil(ChatMediaCache.read(other, key: "abc", root: root), "another source's ticks are its own")
    }

    // MARK: The rows

    func testAChatSittingsRowsCarryTheirFilesAndOtherConversationsDoNot() {
        let photo = EpisodeAttachment(kind: "image", name: "photo-3.jpg", size: 2048)
        let whatsApp = doc(origin: "whatsapp", chat: chat, turns: [("2026-11-04T10:00:00+00:00", [photo])])
        let blocks = ReaderLayout.blocks(doc: whatsApp, scalars: ScalarText(whatsApp.text), focus: nil, focusStyle: .focus)
        let files = ReaderChat.rows(blocks: blocks, doc: whatsApp).compactMap { row -> [ChatFile]? in
            if case let .message(m) = row.kind { return m.extras?.files }
            return nil
        }.flatMap { $0 }
        XCTAssertEqual(files.map(\.name), ["photo-3.jpg"])
        let export = doc(origin: "chatgpt-export", chat: chat, turns: [("2026-11-04T10:00:00+00:00", [photo])])
        let other = ReaderChat.rows(blocks: ReaderLayout.blocks(doc: export, scalars: ScalarText(export.text), focus: nil,
                                                                focusStyle: .focus), doc: export)
            .compactMap { row -> [ChatFile]? in
                if case let .message(m) = row.kind { return m.extras?.files }
                return nil
            }.flatMap { $0 }
        XCTAssertTrue(other.isEmpty, "an export's attachment stays a Tag")
    }

    func testAPicturesTileKeepsItsAspectWithinTheSide() {
        let wide = ChatMediaTile.fitted(CGSize(width: 400, height: 200), side: 220)
        XCTAssertEqual(wide.width, 220, accuracy: 0.01)
        XCTAssertEqual(wide.height, 110, accuracy: 0.01)
        XCTAssertEqual(ChatMediaTile.fitted(CGSize(width: 100, height: 2000), side: 220).width, 220 / 3, accuracy: 0.01)
        XCTAssertEqual(ChatMediaTile.fitted(.zero, side: 220), CGSize(width: 220, height: 220))
    }
}

private actor AskLog {
    var lines: [String] = []
    func add(_ line: String) { lines.append(line) }
}
