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
    /// chats-ux-v2 — the person's chat with themselves ("message yourself"): its JID is their own account's.
    var isSelf = false
    /// chats-ux-v2 — where WhatsApp keeps this chat's profile picture, relative to its container (app-side only, never
    /// posted); nil when WhatsApp holds none.
    var picturePath: String? = nil

    /// What the picker's search matches beyond the name: the digits of a one-to-one chat's number (app-side only).
    var searchDigits: String { phoneHandle.map { $0.filter(\.isNumber) } ?? "" }

    /// The number in a one-to-one JID (`<digits>@s.whatsapp.net`) as a phone handle, for Contacts only.
    var phoneHandle: String? { group ? nil : Self.phoneHandle(jid: jid) }

    /// A person's JID (`<digits>@s.whatsapp.net`) as a phone handle, for Contacts only — never posted.
    static func phoneHandle(jid: String) -> String? {
        guard let at = jid.firstIndex(of: "@"), jid[at...] == "@s.whatsapp.net" else { return nil }
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
/// **Mentions.** WhatsApp stores an @mention as the person's number in the words, in groups and one-to-one chats
/// alike; it is replaced here with their name when WhatsApp or Contacts knows it, else "@someone", so no number is posted (the backend's scrub has
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

    /// Status updates, channels and broadcast lists are nobody's conversation — every shape a real store holds
    /// (`@status`, `@lid.status`, `@newsletter`, `@broadcast`; structure check 2026-10-29).
    static func isListed(jid: String) -> Bool {
        !(jid.isEmpty || jid == "status@broadcast" || jid.hasSuffix("@newsletter") || jid.hasSuffix("@broadcast")
          || jid.hasSuffix("@status") || jid.hasSuffix(".status"))
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
        let own = ownAccounts()
        return try withCopy { db in
            let have = try Self.columns("ZWACHATSESSION", db)
            guard have.contains("ZCONTACTJID") else { throw WhatsAppReadError.unreadable }
            // chats-ux-v2 — each chat's profile picture, where WhatsApp keeps one (`ZWAPROFILEPICTUREITEM`: the JID and
            // the file's path in the container), read only where this Mac's copy has the table.
            let pics = try Self.columns("ZWAPROFILEPICTUREITEM", db)
            let joinPics = pics.contains("ZJID") && pics.contains("ZPATH")
            let sql = """
                SELECT s.Z_PK AS pk, s.ZCONTACTJID AS jid, \(Self.pick("ZPARTNERNAME", from: "s", in: have, as: "name")),
                       \(Self.pick("ZLASTMESSAGEDATE", from: "s", in: have, as: "last")),
                       \(joinPics ? "(SELECT MAX(p.ZPATH) FROM ZWAPROFILEPICTUREITEM p WHERE p.ZJID = s.ZCONTACTJID)"
                                  : "NULL") AS picture
                FROM ZWACHATSESSION s ORDER BY last DESC
                """
            var out: [WhatsAppChat] = []
            for row in try db.query(sql, binds: []) {
                guard let pk = Self.int(row["pk"]), let jid = row["jid"] as? String, Self.isListed(jid: jid) else { continue }
                let id = Self.chatId(jid: jid)
                if let ids, !ids.contains(id) { continue }
                let group = jid.hasSuffix("@g.us")
                out.append(WhatsAppChat(id: id, sessionPk: pk, jid: jid, partnerName: (row["name"] as? String) ?? "",
                                        group: group,
                                        lastActivity: (row["last"] as? NSNumber).map {
                                            Date(timeIntervalSinceReferenceDate: $0.doubleValue) },
                                        isSelf: !group && own.contains(Self.account(jid: jid)),
                                        picturePath: (row["picture"] as? String).flatMap { $0.isEmpty ? nil : $0 }))
                if ids == nil && out.count >= listLimit { break }
            }
            return out
        }
    }

    // MARK: The person's own chat and the chats' pictures (chats-ux-v2)

    /// The container the store lives in (its own folder: tests point the store elsewhere).
    var containerFolder: URL { store.deletingLastPathComponent() }

    /// The account part of a JID (`<digits>@s.whatsapp.net`, `<digits>@lid` → the digits), lower-cased.
    static func account(jid: String) -> String {
        String(jid.split(separator: "@", maxSplits: 1).first ?? "").lowercased()
    }

    /// The keys WhatsApp's shared preferences keep the person's own identities under (structure check on a real
    /// install, 2026-10-29, names only): the phone JID (`OwnJabberID`, `LastOwnJabberID`, `…@s.whatsapp.net`) and the
    /// linked-identity id (`lid`, `lidd`, `…@lid`) — the self-chat's session carries the LID, not the phone JID.
    static let ownIdentityKeys = ["OwnJabberID", "LastOwnJabberID", "lid", "lidd"]

    /// The person's own accounts (the account part of each identity above) — read from this Mac's container, never
    /// posted. Only a string value that is a phone JID or a LID counts. Empty when the file or keys are absent: then
    /// no chat is taken for the person's own.
    func ownAccounts() -> Set<String> {
        let plist = containerFolder.appendingPathComponent("Library/Preferences/group.net.whatsapp.WhatsApp.shared.plist")
        guard let data = try? Data(contentsOf: plist), data.count < 4 * 1024 * 1024,
              let dict = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
        else { return [] }
        var out: Set<String> = []
        for key in Self.ownIdentityKeys {
            guard let text = dict[key] as? String,
                  text.hasSuffix("@s.whatsapp.net") || text.hasSuffix("@lid") else { continue }
            let account = Self.account(jid: text)
            if account.count >= 6, account.allSatisfy(\.isNumber) { out.insert(account) }
        }
        return out
    }

    /// A chat's profile picture as WhatsApp keeps it on this Mac, made at most 128 px (PNG) — only a regular file inside
    /// the container, under 8 MB; nil otherwise. Read from WhatsApp's own file (no copy needed: a whole small file).
    func picture(_ chat: WhatsAppChat) -> Data? {
        guard let path = chat.picturePath, !path.contains("..") else { return nil }
        let root = containerFolder.resolvingSymlinksInPath().standardizedFileURL
        let base = path.hasPrefix("/") ? URL(fileURLWithPath: path) : root.appendingPathComponent(path)
        for candidate in [base, base.appendingPathExtension("thumb"), base.appendingPathExtension("jpg")] {
            let file = candidate.resolvingSymlinksInPath().standardizedFileURL
            guard file.path.hasPrefix(root.path + "/"),
                  let values = try? file.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey]),
                  values.isRegularFile == true, (values.fileSize ?? 0) > 0,
                  (values.fileSize ?? 0) < MessagesSharedPhotos.maxFileBytes else { continue }
            if let small = MessagesSharedPhotos.downsized(file) { return small }
        }
        return nil
    }

    // MARK: A ticked chat

    /// One batch of a ticked chat past `cursor`, plus — when `recheck` — the bounded re-read of the recheck window.
    /// `contact` is a one-to-one chat's card as posted, `memberCards` each group member's by JID (`postedCard`:
    /// the ONE card's Contacts id, `""` when looked up and none or several hold the handle, absent when not looked up).
    func read(_ chat: WhatsAppChat, name: String, memberNames: [String: String], since cursor: Int64,
              recheck: Bool = true, contact: String? = nil, memberCards: [String: String] = [:]) throws -> WhatsAppPass {
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
            var memberJids: [String: String] = [:]
            var mentionNames = memberNames
            if !chat.group, !name.isEmpty { mentionNames[chat.jid] = name }
            for row in rows {
                guard let pk = Self.int(row["pk"]), let stanza = row["stanza"] as? String, !stanza.isEmpty,
                      let date = row["date"] as? NSNumber else { continue }
                var message: [String: Any] = ["rowid": pk, "stanza": stanza, "date": date.doubleValue,
                                              "fromMe": (Self.int(row["from_me"]) ?? 0) != 0,
                                              "type": Self.int(row["type"]) ?? 0]
                if let text = row["text"] as? String {
                    // Every chat, not only groups: a one-to-one chat's @mention of the other side reads as their name.
                    message["text"] = Self.namingMentions(text, names: mentionNames)
                }
                if let jid = row["member_jid"] as? String, !jid.isEmpty, chat.group {
                    let key = Self.memberKey(chatJid: chat.jid, memberJid: jid)
                    message["member"] = key
                    members[key] = memberNames[jid] ?? ""
                    memberJids[key] = jid
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
                conversation["members"] = members.sorted { $0.key < $1.key }.map { member -> [String: Any] in
                    var out: [String: Any] = ["key": member.key, "name": member.value]
                    // The member's address-book card by Contacts id (one person across sources), never the JID.
                    if let jid = memberJids[member.key], let card = memberCards[jid] { out["contact"] = card }
                    return out
                }
            } else if chat.isSelf {
                // chats-ux-v2: the person's notes to themselves — every word theirs, no other side, no card.
                conversation["selfChat"] = true
            } else if let contact {
                conversation["contact"] = contact
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

    /// Every member JID of a group (named by WhatsApp or not) — for the app's own Contacts look-up, never posted.
    func memberJids(_ chat: WhatsAppChat) throws -> [String] {
        try withCopy { db in
            let have = try Self.columns("ZWAGROUPMEMBER", db)
            guard have.contains("ZMEMBERJID"), have.contains("ZCHATSESSION") else { return [] }
            return try db.query("SELECT ZMEMBERJID AS jid FROM ZWAGROUPMEMBER WHERE ZCHATSESSION = ?1",
                                binds: [.int(chat.sessionPk)]).compactMap { $0["jid"] as? String }.filter { !$0.isEmpty }
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
