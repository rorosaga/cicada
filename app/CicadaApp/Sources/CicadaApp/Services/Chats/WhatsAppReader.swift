import CryptoKit
import Foundation

/// One WhatsApp chat as the tick list shows it. App-side only: `jid` (it carries the phone number) is used to find the
/// contact's name and photo on this Mac and is never posted; the backend knows the chat by `id`, a hash of the JID.
struct WhatsAppChat: Identifiable, Equatable, Sendable {
    let id: String
    let sessionPk: Int64
    let jid: String
    let partnerName: String
    let group: Bool
    let lastActivity: Date?

    /// The number in a one-to-one JID (`<digits>@s.whatsapp.net`) as a phone handle, for Contacts only.
    var phoneHandle: String? {
        guard !group, let at = jid.firstIndex(of: "@"), jid[at...] == "@s.whatsapp.net" else { return nil }
        let digits = jid[..<at]
        return digits.allSatisfy(\.isNumber) && digits.count >= 6 ? "+" + digits : nil
    }
}

/// One read of a ticked chat, serialised off the main actor and ready to post.
struct WhatsAppPass: Sendable {
    var json: Data
    var cursor: Int64
    var count: Int
    var hasMore: Bool
}

/// G179 (2026-10-28) — WhatsApp Desktop's own store, read the Messages way: the APP reads (Full Disk Access also covers
/// another app's group container without the "access data from other apps" prompt), from a COPY — `ChatStorage.sqlite`
/// and its `-wal`, APFS-cloned into a private 0700 temp folder, so WhatsApp's own file is never held open — and posts a
/// projection; the backend parses it (`api/services/whatsapp_source.py`). The store is the iOS app's Core Data schema
/// (public forensic write-ups and open-source exporters); every column is read only where this Mac's copy has it
/// (`PRAGMA table_info`), so a WhatsApp update that renames one stops that field, never the sync.
///
/// **What it reads.** For the list: each chat's JID (hashed for the backend; its number used only for Contacts here),
/// WhatsApp's partner or group name and last activity. Status updates and channels (`status@broadcast`,
/// `@newsletter`) are nobody's conversation and are never listed. For a TICKED chat only: each message's id, stanza
/// id, time, direction, words, type, its group member (as a participant key: a hash of the chat's and the member's
/// JID), the quoted-reply metadata blob (base64), and its media item's title, file NAME and size — never
/// `ZMEDIALOCALPATH`'s folders, never a file's bytes, never a vCard or coordinates.
///
/// **Cursor.** Two reads, so new messages are always reached (#502 review B1): every batch is the rows past the chat's
/// highest `ZWAMESSAGE.Z_PK` posted, oldest first; the FIRST batch of a pass also re-reads the already-posted rows of
/// the last `recheckWindow`, newest first and at most `recheckLimit` (a delete for everyone or an edit rewrites its
/// row in place) — a separate, bounded read, so a busy chat's window can never crowd new rows out of a batch.
/// Re-posting an unchanged row is free: the backend's stager skips it. The cursor moves past every row a batch saw,
/// readable or not, so a run of rows with no stanza id cannot stall it.
///
/// **Mentions.** WhatsApp stores a group @mention as the member's number in the words; it is replaced here with the
/// member's name when WhatsApp or Contacts knows it, else "@someone", so no number is posted (the backend's scrub has
/// its own phone rule as a second line).
struct WhatsAppReader: Sendable {
    let store: URL
    var scratchRoot: URL = FileManager.default.temporaryDirectory
    var batchLimit = 500
    var listLimit = 300
    var recheckWindow: TimeInterval = 48 * 3600
    /// At most this many already-posted rows are re-read per pass (the newest first).
    var recheckLimit = 500
    var now: @Sendable () -> Date = { Date() }

    static var container: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Group Containers/group.net.whatsapp.WhatsApp.shared", isDirectory: true)
    }

    static var standardStore: URL { container.appendingPathComponent("ChatStorage.sqlite") }

    /// The id the backend sees: a hash of the JID, never the number in it (`chat_live.hash_id`'s shape).
    static func chatId(jid: String) -> String { hash([jid]) }

    /// A group member's participant key: the chat's and the member's JID, hashed together — never links two chats.
    static func memberKey(chatJid: String, memberJid: String) -> String { hash([chatJid, memberJid]) }

    private static func hash(_ parts: [String]) -> String {
        let joined = parts.joined(separator: "\u{1f}")
        return SHA256.hash(data: Data(joined.utf8)).map { String(format: "%02x", $0) }.joined().prefix(24).description
    }

    static func isListed(jid: String) -> Bool {
        !(jid.isEmpty || jid == "status@broadcast" || jid.hasSuffix("@newsletter") || jid.hasSuffix("@broadcast"))
    }

    func checkAccess() throws {
        do {
            let handle = try FileHandle(forReadingFrom: store)
            try handle.close()
        } catch {
            let ns = error as NSError
            if ns.domain == NSCocoaErrorDomain && (ns.code == NSFileNoSuchFileError || ns.code == NSFileReadNoSuchFileError) {
                throw BrowserFileError.missing(.whatsAppStore, [store.path])
            }
            throw BrowserFileError.classify(error, file: .whatsAppStore, path: store.path)
        }
    }

    /// Clone the store and its WAL into a private folder, open the copy, run `body` in one read transaction.
    private func withCopy<T>(_ body: (SQLiteReadOnly) throws -> T) throws -> T {
        try checkAccess()
        let fm = FileManager.default
        let folder = scratchRoot.appendingPathComponent("cicada-whatsapp-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        defer { try? fm.removeItem(at: folder) }
        let copy = folder.appendingPathComponent("ChatStorage.sqlite")
        do {
            try fm.copyItem(at: store, to: copy)
            let wal = URL(fileURLWithPath: store.path + "-wal")
            if fm.fileExists(atPath: wal.path) { try fm.copyItem(at: wal, to: URL(fileURLWithPath: copy.path + "-wal")) }
        } catch {
            throw BrowserFileError.classify(error, file: .whatsAppStore, path: store.path)
        }
        let db: SQLiteReadOnly
        do { db = try SQLiteReadOnly(url: copy) } catch { throw WhatsAppReadError.unreadable }
        defer { db.close() }
        do {
            try db.exec("BEGIN")
            defer { try? db.exec("COMMIT") }
            return try body(db)
        } catch let error as WhatsAppReadError {
            throw error
        } catch {
            throw WhatsAppReadError.unreadable
        }
    }

    private static func columns(_ table: String, _ db: SQLiteReadOnly) throws -> Set<String> {
        Set(try db.query("PRAGMA table_info(\(table))", binds: []).compactMap { $0["name"] as? String })
    }

    private static func pick(_ column: String, from table: String, in present: Set<String>, as alias: String) -> String {
        present.contains(column) ? "\(table).\(column) AS \(alias)" : "NULL AS \(alias)"
    }

    // MARK: The list

    func chats(ids: Set<String>? = nil) throws -> [WhatsAppChat] {
        try withCopy { db in
            let have = try Self.columns("ZWACHATSESSION", db)
            guard have.contains("ZCONTACTJID") else { throw WhatsAppReadError.unreadable }
            let sql = """
                SELECT Z_PK AS pk, ZCONTACTJID AS jid, \(Self.pick("ZPARTNERNAME", from: "ZWACHATSESSION", in: have, as: "name")),
                       \(Self.pick("ZLASTMESSAGEDATE", from: "ZWACHATSESSION", in: have, as: "last"))
                FROM ZWACHATSESSION ORDER BY last DESC
                """
            var out: [WhatsAppChat] = []
            for row in try db.query(sql, binds: []) {
                guard let pk = Self.int(row["pk"]), let jid = row["jid"] as? String, Self.isListed(jid: jid) else { continue }
                let id = Self.chatId(jid: jid)
                if let ids, !ids.contains(id) { continue }
                out.append(WhatsAppChat(id: id, sessionPk: pk, jid: jid, partnerName: (row["name"] as? String) ?? "",
                                        group: jid.hasSuffix("@g.us"),
                                        lastActivity: (row["last"] as? NSNumber).map {
                                            Date(timeIntervalSinceReferenceDate: $0.doubleValue) }))
                if ids == nil && out.count >= listLimit { break }
            }
            return out
        }
    }

    // MARK: A ticked chat

    /// One batch of a ticked chat past `cursor`, plus — when `recheck` — the bounded re-read of the recheck window.
    func read(_ chat: WhatsAppChat, name: String, memberNames: [String: String], since cursor: Int64,
              recheck: Bool = true) throws -> WhatsAppPass {
        try withCopy { db in
            let msg = try Self.columns("ZWAMESSAGE", db)
            let media = try Self.columns("ZWAMEDIAITEM", db)
            let member = try Self.columns("ZWAGROUPMEMBER", db)
            guard msg.contains("ZCHATSESSION"), msg.contains("ZMESSAGEDATE") else { throw WhatsAppReadError.unreadable }
            let joinMedia = media.contains("ZMESSAGE")
            let joinMember = msg.contains("ZGROUPMEMBER") && member.contains("ZMEMBERJID")
            let threshold = now().timeIntervalSinceReferenceDate - recheckWindow
            let select = """
                SELECT m.Z_PK AS pk, \(Self.pick("ZSTANZAID", from: "m", in: msg, as: "stanza")), m.ZMESSAGEDATE AS date,
                       \(Self.pick("ZISFROMME", from: "m", in: msg, as: "from_me")),
                       \(Self.pick("ZTEXT", from: "m", in: msg, as: "text")),
                       \(Self.pick("ZMESSAGETYPE", from: "m", in: msg, as: "type")),
                       \(joinMember ? "g.ZMEMBERJID AS member_jid" : "NULL AS member_jid"),
                       \(joinMedia ? Self.pick("ZMETADATA", from: "i", in: media, as: "metadata") : "NULL AS metadata"),
                       \(joinMedia ? Self.pick("ZTITLE", from: "i", in: media, as: "title") : "NULL AS title"),
                       \(joinMedia ? Self.pick("ZMEDIALOCALPATH", from: "i", in: media, as: "local") : "NULL AS local"),
                       \(joinMedia ? Self.pick("ZFILESIZE", from: "i", in: media, as: "size") : "NULL AS size"),
                       \(joinMedia ? "i.Z_PK AS media_pk" : "NULL AS media_pk")
                FROM ZWAMESSAGE m
                \(joinMedia ? "LEFT JOIN ZWAMEDIAITEM i ON i.ZMESSAGE = m.Z_PK" : "")
                \(joinMember ? "LEFT JOIN ZWAGROUPMEMBER g ON g.Z_PK = m.ZGROUPMEMBER" : "")
                """
            let fresh = try db.query(select + " WHERE m.ZCHATSESSION = ?1 AND m.Z_PK > ?2 ORDER BY m.Z_PK LIMIT \(batchLimit)",
                                     binds: [.int(chat.sessionPk), .int(cursor)], base64Blobs: ["metadata"])
            let again = recheck && cursor > 0
                ? try db.query(select + " WHERE m.ZCHATSESSION = ?1 AND m.Z_PK <= ?2 AND m.ZMESSAGEDATE >= ?3"
                               + " ORDER BY m.Z_PK DESC LIMIT \(recheckLimit)",
                               binds: [.int(chat.sessionPk), .int(cursor), .real(threshold)], base64Blobs: ["metadata"])
                : []
            let rows = again.reversed() + fresh
            // The cursor moves past every fresh row seen, readable or not, so it can never stall on one.
            let next = fresh.compactMap { Self.int($0["pk"]) }.max().map { max($0, cursor) } ?? cursor
            var messages: [[String: Any]] = []
            var members: [String: String] = [:]
            for row in rows {
                guard let pk = Self.int(row["pk"]), let stanza = row["stanza"] as? String, !stanza.isEmpty,
                      let date = row["date"] as? NSNumber else { continue }
                var message: [String: Any] = ["rowid": pk, "stanza": stanza, "date": date.doubleValue,
                                              "fromMe": (Self.int(row["from_me"]) ?? 0) != 0,
                                              "type": Self.int(row["type"]) ?? 0]
                if let text = row["text"] as? String {
                    message["text"] = chat.group ? Self.namingMentions(text, names: memberNames) : text
                }
                if let jid = row["member_jid"] as? String, !jid.isEmpty, chat.group {
                    let key = Self.memberKey(chatJid: chat.jid, memberJid: jid)
                    message["member"] = key
                    members[key] = memberNames[jid] ?? ""
                }
                if let blob = row["metadata"] as? String { message["metadata"] = blob }
                if row["media_pk"] != nil, !(row["media_pk"] is NSNull) {
                    var item: [String: Any] = [:]
                    if let title = row["title"] as? String { item["title"] = title }
                    // The file's own name only — the folders of ZMEDIALOCALPATH never leave the app.
                    if let local = row["local"] as? String, !local.isEmpty {
                        item["file"] = URL(fileURLWithPath: local).lastPathComponent
                    }
                    if let size = Self.int(row["size"]), size > 0 { item["size"] = size }
                    message["media"] = item
                }
                messages.append(message)
            }
            var conversation: [String: Any] = ["id": chat.id, "name": name, "group": chat.group]
            if chat.group {
                conversation["members"] = members.sorted { $0.key < $1.key }.map { ["key": $0.key, "name": $0.value] }
            }
            let body: [String: Any] = ["conversation": conversation, "messages": messages]
            return WhatsAppPass(json: try JSONSerialization.data(withJSONObject: body), cursor: next,
                                count: messages.count, hasMore: fresh.count >= batchLimit)
        }
    }

    /// The newest row of a chat — where a live-only tick starts.
    func newest(_ chat: WhatsAppChat) throws -> Int64 {
        try withCopy { db in
            try db.query("SELECT COALESCE(MAX(Z_PK), 0) AS top FROM ZWAMESSAGE WHERE ZCHATSESSION = ?1",
                         binds: [.int(chat.sessionPk)]).first.flatMap { Self.int($0["top"]) } ?? 0
        }
    }

    /// The names WhatsApp itself keeps for a group's members, by member JID (the app's own, never posted with the JID).
    func memberNames(_ chat: WhatsAppChat) throws -> [String: String] {
        try withCopy { db in
            let have = try Self.columns("ZWAGROUPMEMBER", db)
            guard have.contains("ZMEMBERJID"), have.contains("ZCHATSESSION") else { return [:] }
            let name = have.contains("ZCONTACTNAME") ? "ZCONTACTNAME" : (have.contains("ZFIRSTNAME") ? "ZFIRSTNAME" : "NULL")
            var out: [String: String] = [:]
            for row in try db.query("SELECT ZMEMBERJID AS jid, \(name) AS name FROM ZWAGROUPMEMBER WHERE ZCHATSESSION = ?1",
                                    binds: [.int(chat.sessionPk)]) {
                if let jid = row["jid"] as? String, let n = row["name"] as? String, !n.isEmpty { out[jid] = n }
            }
            return out
        }
    }

    private static let mention = try! NSRegularExpression(pattern: "(?<![\\w@])@\\+?(\\d{6,15})(?!\\w)")

    /// A group @mention (`@<number>`) as the member's name where WhatsApp or Contacts knows it, else "@someone".
    static func namingMentions(_ text: String, names: [String: String]) -> String {
        let ns = text as NSString
        var out = text
        for match in mention.matches(in: text, range: NSRange(location: 0, length: ns.length)).reversed() {
            let digits = ns.substring(with: match.range(at: 1))
            let name = names["\(digits)@s.whatsapp.net"].flatMap { $0.isEmpty ? nil : $0 }
            let replaced = (out as NSString).replacingCharacters(in: match.range, with: "@" + (name ?? "someone"))
            out = replaced
        }
        return out
    }

    static func int(_ value: Any?) -> Int64? {
        switch value {
        case let n as NSNumber: n.int64Value
        case let s as String: Int64(s)
        default: nil
        }
    }
}

enum WhatsAppReadError: Error, LocalizedError, Equatable {
    case unreadable
    /// A full batch that left the cursor where it was — reported, never retried in a loop.
    case stalled
    var errorDescription: String? {
        switch self {
        case .unreadable: Copy.Chats.whatsAppUnreadable
        case .stalled: Copy.Chats.whatsAppStalled
        }
    }
}
