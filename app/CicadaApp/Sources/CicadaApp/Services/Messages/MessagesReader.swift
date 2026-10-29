import CryptoKit
import Foundation

enum MessagesReadError: Error, LocalizedError, Equatable {
    case unreadable(String)
    var errorDescription: String? {
        switch self {
        case .unreadable(let detail): "Couldn't read Messages: \(detail)"
        }
    }
}

/// G179 — reads the Messages database the way the Awake rail allows: the APP opens `~/Library/Messages/chat.db`
/// (Full Disk Access is the only way in; the launchd backend never opens it), read-only, inside one read transaction.
///
/// **What it reads.** For the list: each chat's id, its handle (to find the contact's name and photo on this Mac —
/// never sent), its own display name, the last message's time and how many messages each side sent. A group chat
/// (`chat.style` 43, 2026-10-28) is listed too, with its members' handles — kept in the app, used only to find their
/// Contacts names; each member crosses as a participant key (`memberKey`), never the handle. For a TICKED chat only: each message row's id, guid, time,
/// direction, `text` and `attributedBody` (the archived words, sent as base64 for the backend to decode), its
/// reaction/event columns, its edit and unsend times, and its attachments' *names* and types — never
/// `attachment.filename` (a path) and never an attachment's bytes. No other column, no other chat. Since 2026-10-20
/// (what made it a conversation): a tapback's target and emoji (`associated_message_guid`, `associated_message_emoji`),
/// an inline reply's target (`thread_originator_guid`) and whether an attachment is a sticker (`is_sticker`) — ids
/// and a flag, each read only where this Mac's `chat.db` has the column (`PRAGMA table_info`), so an older macOS
/// still syncs without them.
///
/// **Which chats.** The Settings list is the `listLimit` most recent chats; a ticked chat is read by its own id
/// (`conversations(ids:)`), whatever its rank, so a quiet chat that falls below the list's cap never stops syncing.
///
/// **Cursor.** Past `message.ROWID`, `batchLimit` rows at a time, plus every row already posted whose edit or unsend
/// time (an edit keeps its old ROWID) differs from the one the cursor recorded for it. The cursor records each row
/// edited or unsent within the last `editWindow` (by its edit time) and every pass re-checks exactly that window, so an
/// edit that reaches this Mac late, carrying an earlier edit time than one already seen, is still found. Outside the
/// window nothing is re-checked: an edit that arrives more than `editWindow` after it was made is not seen.
struct MessagesReader: Sendable {
    let database: URL
    var batchLimit = 500
    var listLimit = 200
    /// How far back, by edit time, every pass re-checks the rows it already posted for an edit or an unsend.
    var editWindow: TimeInterval = 30 * 24 * 3600
    /// At most this many edited rows are re-checked per pass (the newest edits first).
    var editCheckLimit = 5000
    var now: @Sendable () -> Date = { Date() }

    static var standardDatabase: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Messages/chat.db")
    }

    /// The conversation id the backend sees: a hash of `chat.guid`, never the address inside it.
    static func conversationId(chatGuid: String) -> String {
        SHA256.hash(data: Data(chatGuid.utf8)).map { String(format: "%02x", $0) }.joined().prefix(24).description
    }

    /// Opening the file first classifies a refused read as the Full Disk Access fix and an absent one as missing.
    func checkAccess() throws {
        do {
            let handle = try FileHandle(forReadingFrom: database)
            try handle.close()
        } catch {
            let ns = error as NSError
            if ns.domain == NSCocoaErrorDomain && ns.code == NSFileNoSuchFileError {
                throw BrowserFileError.missing(.messagesDatabase, [database.path])
            }
            throw BrowserFileError.classify(error, file: .messagesDatabase, path: database.path)
        }
    }

    private func open() throws -> SQLiteReadOnly {
        try checkAccess()
        do {
            return try SQLiteReadOnly(url: database)
        } catch {
            throw MessagesReadError.unreadable(String(describing: error))
        }
    }

    static let conversationsSelect = """
        SELECT c.ROWID AS chat, c.guid AS guid, c.chat_identifier AS handle, COALESCE(c.display_name, '') AS name,
               COALESCE(c.service_name, '') AS service, COALESCE(c.style, 45) AS style,
               (SELECT MAX(j.message_date) FROM chat_message_join j WHERE j.chat_id = c.ROWID) AS last,
               (SELECT COUNT(*) FROM chat_message_join j JOIN message m ON m.ROWID = j.message_id
                 WHERE j.chat_id = c.ROWID AND m.is_from_me = 1 AND COALESCE(m.associated_message_type, 0) = 0
                   AND COALESCE(m.item_type, 0) = 0) AS from_me,
               (SELECT COUNT(*) FROM chat_message_join j JOIN message m ON m.ROWID = j.message_id
                 WHERE j.chat_id = c.ROWID AND m.is_from_me = 0 AND COALESCE(m.associated_message_type, 0) = 0
                   AND COALESCE(m.item_type, 0) = 0) AS from_them,
               (COALESCE(c.style, 45) = 45 AND COALESCE(c.chat_identifier, '') <> ''
                 AND (c.chat_identifier = c.last_addressed_handle
                      OR c.chat_identifier IN (SELECT substr(o.account_login, 3) FROM chat o
                                               WHERE o.account_login LIKE '_:%'))) AS own
        FROM chat c
        WHERE COALESCE(c.style, 45) IN (45, 43)
        """
    static let conversationsSQL = conversationsSelect + " ORDER BY last DESC"

    /// Every conversation, one-to-one and group, most recent first, at most `listLimit` — the Settings picker's list
    /// only.
    func conversations() throws -> [MessagesConversation] {
        let db = try open()
        defer { db.close() }
        do {
            try db.exec("BEGIN")
            defer { try? db.exec("COMMIT") }
            let rows = try db.query(Self.conversationsSQL + " LIMIT \(listLimit)", binds: [])
            return try Self.withMembers(rows.compactMap(Self.conversation), in: db)
        } catch {
            throw MessagesReadError.unreadable(String(describing: error))
        }
    }

    /// Each group's members' handles (`chat_handle_join`), for the app's own Contacts look-up — never sent.
    static func withMembers(_ list: [MessagesConversation], in db: SQLiteReadOnly) throws -> [MessagesConversation] {
        let groups = list.filter(\.isGroup).map(\.chatRowId)
        guard !groups.isEmpty else { return list }
        let marks = Array(repeating: "?", count: groups.count).joined(separator: ", ")
        var members: [Int64: [String]] = [:]
        for row in try db.query("SELECT j.chat_id AS chat, h.id AS handle FROM chat_handle_join j "
                                + "JOIN handle h ON h.ROWID = j.handle_id WHERE j.chat_id IN (\(marks)) "
                                + "ORDER BY j.chat_id, h.ROWID", binds: groups.map { .int($0) }) {
            if let chat = int(row["chat"]), let handle = row["handle"] as? String, !handle.isEmpty {
                members[chat, default: []].append(handle)
            }
        }
        return list.map { c in
            var c = c
            if c.isGroup { c.members = members[c.chatRowId] ?? [] }
            return c
        }
    }

    /// A group member's participant key: stable per chat, a hash of the chat's id and the member's handle — so it
    /// never carries the phone number or address, and never links two chats by itself (G179 groups).
    static func memberKey(conversationId: String, handle: String) -> String {
        SHA256.hash(data: Data("member:\(conversationId):\(handle)".utf8)).map { String(format: "%02x", $0) }.joined()
            .prefix(24).description
    }

    /// The one-to-one conversations with these ids, whatever their rank: what every pass reads, so a ticked chat
    /// never falls off the end of the list. The id is a hash of `chat.guid`, so the chats' guids are hashed here (no
    /// words, no counts) and only the matches are described.
    func conversations(ids: Set<String>) throws -> [MessagesConversation] {
        guard !ids.isEmpty else { return [] }
        let db = try open()
        defer { db.close() }
        let rows: [[String: Any]]
        do {
            try db.exec("BEGIN")
            defer { try? db.exec("COMMIT") }
            let chats = try db.query("SELECT ROWID AS chat, guid FROM chat WHERE COALESCE(style, 45) IN (45, 43)",
                                     binds: [])
            let wanted = chats.compactMap { row -> Int64? in
                guard let chat = Self.int(row["chat"]), let guid = row["guid"] as? String, !guid.isEmpty,
                      ids.contains(Self.conversationId(chatGuid: guid)) else { return nil }
                return chat
            }
            guard !wanted.isEmpty else { return [] }
            let marks = Array(repeating: "?", count: wanted.count).joined(separator: ", ")
            rows = try db.query(Self.conversationsSelect + " AND c.ROWID IN (\(marks)) ORDER BY last DESC",
                                binds: wanted.map { .int($0) })
            return try Self.withMembers(rows.compactMap(Self.conversation), in: db)
        } catch {
            throw MessagesReadError.unreadable(String(describing: error))
        }
    }

    private static func conversation(_ row: [String: Any]) -> MessagesConversation? {
        guard let chat = int(row["chat"]), let guid = row["guid"] as? String, !guid.isEmpty else { return nil }
        let fromMe = Int(int(row["from_me"]) ?? 0), fromThem = Int(int(row["from_them"]) ?? 0)
        guard fromMe + fromThem > 0 else { return nil }
        return MessagesConversation(
            id: conversationId(chatGuid: guid), chatRowId: chat, handle: (row["handle"] as? String) ?? "",
            displayName: (row["name"] as? String) ?? "", service: service(row["service"] as? String),
            lastActivity: int(row["last"]).flatMap(date), fromMe: fromMe, fromThem: fromThem,
            isGroup: int(row["style"]) == 43, isSelf: (int(row["own"]) ?? 0) != 0)
    }

    /// The optional `message` columns a pass reads when this Mac's database has them — ids and an emoji, never words.
    static let optionalMessageColumns = ["associated_message_guid", "associated_message_emoji", "thread_originator_guid"]

    /// The rows past the cursor's ROWID, plus `recheck` already-posted rows whose edit or unsend changed. `extra` names
    /// the optional columns this database has (`optionalMessageColumns`).
    static func rowsSQL(recheck: Int, extra: [String] = []) -> String {
        let changed = recheck > 0 ? " OR m.ROWID IN (\(Array(repeating: "?", count: recheck).joined(separator: ", ")))" : ""
        let optional = extra.filter(optionalMessageColumns.contains).map { "m.\($0) AS \($0), " }.joined()
        return """
            SELECT m.ROWID AS rowid, m.guid AS guid, m.date AS date, m.is_from_me AS is_from_me, m.text AS text,
                   m.attributedBody AS attributed_body, \(optional)
                   COALESCE(m.associated_message_type, 0) AS associated_message_type, COALESCE(m.item_type, 0) AS item_type,
                   COALESCE(m.is_system_message, 0) AS is_system_message, COALESCE(m.date_edited, 0) AS date_edited,
                   COALESCE(m.date_retracted, 0) AS date_retracted, COALESCE(h.id, '') AS sender_handle
            FROM message m JOIN chat_message_join j ON j.message_id = m.ROWID
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            WHERE j.chat_id = ?1 AND (m.ROWID > ?2\(changed))
            ORDER BY m.ROWID
            """
    }

    /// The edit or unsend time of every already-posted row edited or unsent within the window — what each pass compares
    /// against the cursor's record. Only ids and times, never a word.
    static let editStampsSQL = """
        SELECT m.ROWID AS rowid, MAX(COALESCE(m.date_edited, 0), COALESCE(m.date_retracted, 0)) AS stamp
        FROM message m JOIN chat_message_join j ON j.message_id = m.ROWID
        WHERE j.chat_id = ?1 AND m.ROWID <= ?2
          AND (COALESCE(m.date_edited, 0) >= ?3 OR COALESCE(m.date_retracted, 0) >= ?3)
        ORDER BY stamp DESC
        """

    /// The window's start as an edit time (Apple nanoseconds — every macOS that edits or unsends stores them so).
    var editThreshold: Int64 {
        let seconds = now().timeIntervalSinceReferenceDate - editWindow
        return max(1, Int64(seconds * 1_000_000_000))
    }

    /// One batch of a ticked conversation's rows past `cursor`, serialised as the sync request. `members` is a group's
    /// members as posted (participant key, the name the person sees, their own one-to-one chat's id) — never a handle.
    func read(_ conversation: MessagesConversation, name: String, members: [MessagesMemberPayload] = [],
              contact: String? = nil, since cursor: MessagesCursor) throws -> MessagesPass {
        let db = try open()
        defer { db.close() }
        var rows: [[String: Any]] = []
        var attachments: [Int64: [[String: Any]]] = [:]
        let threshold = editThreshold
        var stamps: [Int64: Int64] = [:]
        var changed: [Int64] = []
        var recheck: [Int64] = []
        do {
            try db.exec("BEGIN")
            defer { try? db.exec("COMMIT") }
            for row in try db.query(Self.editStampsSQL + " LIMIT \(editCheckLimit)",
                                    binds: [.int(conversation.chatRowId), .int(cursor.rowid), .int(threshold)]) {
                if let rowid = Self.int(row["rowid"]), let stamp = Self.int(row["stamp"]) { stamps[rowid] = stamp }
            }
            changed = stamps.filter { cursor.edits[$0.key] != $0.value }.keys.sorted()
            recheck = Array(changed.prefix(batchLimit))
            let messageColumns = try Self.columns(of: "message", in: db)
            let stickerColumn = try Self.columns(of: "attachment", in: db).contains("is_sticker")
            rows = try db.query(Self.rowsSQL(recheck: recheck.count,
                                             extra: Self.optionalMessageColumns.filter(messageColumns.contains))
                                + " LIMIT \(batchLimit)",
                                binds: [.int(conversation.chatRowId), .int(cursor.rowid)] + recheck.map { .int($0) },
                                base64Blobs: ["attributed_body"])
            let ids = rows.compactMap { Self.int($0["rowid"]) }
            if !ids.isEmpty {
                let marks = Array(repeating: "?", count: ids.count).joined(separator: ", ")
                let found = try db.query(
                    "SELECT j.message_id AS message, a.transfer_name AS name, a.mime_type AS mime, a.uti AS uti, "
                    + "COALESCE(a.total_bytes, 0) AS bytes"
                    + (stickerColumn ? ", COALESCE(a.is_sticker, 0) AS sticker" : "") + " FROM attachment a "
                    + "JOIN message_attachment_join j ON j.attachment_id = a.ROWID "
                    + "WHERE j.message_id IN (\(marks)) ORDER BY j.message_id, a.ROWID",
                    binds: ids.map { .int($0) })
                for att in found {
                    guard let message = Self.int(att["message"]) else { continue }
                    var item: [String: Any] = ["name": (att["name"] as? String) ?? "",
                                               "totalBytes": Self.int(att["bytes"]) ?? 0]
                    if let mime = att["mime"] as? String { item["mimeType"] = mime }
                    if let uti = att["uti"] as? String { item["uti"] = uti }
                    if (Self.int(att["sticker"]) ?? 0) != 0 { item["isSticker"] = true }
                    attachments[message, default: []].append(item)
                }
            }
        } catch {
            throw MessagesReadError.unreadable(String(describing: error))
        }
        // The window as it stands now: rows outside it drop out of the record (it stays bounded); a changed row this
        // batch did not reach keeps its old record so the next batch picks it up.
        var next = MessagesCursor(rowid: cursor.rowid, edits: stamps)
        let reached = Set(rows.compactMap { Self.int($0["rowid"]) })
        for rowid in changed where !reached.contains(rowid) { next.edits[rowid] = cursor.edits[rowid] }
        var messages: [[String: Any]] = []
        for row in rows {
            guard let rowid = Self.int(row["rowid"]) else { continue }
            if rowid > next.rowid { next.rowid = rowid }
            let edited = Self.int(row["date_edited"]) ?? 0, retracted = Self.int(row["date_retracted"]) ?? 0
            let stamp = max(edited, retracted)
            if stamp >= threshold { next.edits[rowid] = stamp }
            var message: [String: Any] = [
                "rowid": rowid, "guid": (row["guid"] as? String) ?? "", "date": Self.int(row["date"]) ?? 0,
                "isFromMe": (Self.int(row["is_from_me"]) ?? 0) != 0,
                "associatedMessageType": Self.int(row["associated_message_type"]) ?? 0,
                "itemType": Self.int(row["item_type"]) ?? 0,
                "isSystemMessage": (Self.int(row["is_system_message"]) ?? 0) != 0,
                "dateEdited": edited, "dateRetracted": retracted,
                "attachments": attachments[rowid] ?? [],
            ]
            if let text = row["text"] as? String { message["text"] = text }
            // A group row's sender, as its participant key — never the handle (G179 groups).
            if conversation.isGroup, !(Self.int(row["is_from_me"]).map { $0 != 0 } ?? false),
               let handle = row["sender_handle"] as? String, !handle.isEmpty {
                message["sender"] = Self.memberKey(conversationId: conversation.id, handle: handle)
            }
            if let body = row["attributed_body"] as? String { message["attributedBody"] = body }
            // A tapback's target and emoji, an inline reply's target: ids, never words (2026-10-20).
            for (column, key) in [("associated_message_guid", "associatedMessageGuid"),
                                  ("associated_message_emoji", "associatedMessageEmoji"),
                                  ("thread_originator_guid", "threadOriginatorGuid")] {
                if let value = row[column] as? String, !value.isEmpty { message[key] = value }
            }
            messages.append(message)
        }
        var conv: [String: Any] = ["id": conversation.id, "name": name, "displayName": conversation.displayName,
                                   "service": conversation.service, "group": conversation.isGroup,
                                   "fromMe": conversation.fromMe, "fromThem": conversation.fromThem]
        if conversation.isGroup { conv["members"] = members.map(\.json) }
        if conversation.isSelf {
            conv["selfChat"] = true        // chats-ux-v2: a note to self — every line the person's, no card
        } else if !conversation.isGroup, let contact {
            conv["contact"] = contact
        }
        let body: [String: Any] = ["conversation": conv, "messages": messages]
        return MessagesPass(json: try JSONSerialization.data(withJSONObject: body), cursor: next,
                            count: messages.count, hasMore: rows.count == batchLimit)
    }

    // MARK: helpers

    /// The column names of one of `chat.db`'s tables, so a column a newer macOS added is read only where it exists.
    static func columns(of table: String, in db: SQLiteReadOnly) throws -> Set<String> {
        Set(try db.query("PRAGMA table_info(\(table))", binds: []).compactMap { $0["name"] as? String })
    }

    static func int(_ value: Any?) -> Int64? {
        switch value {
        case let n as NSNumber: n.int64Value
        case let s as String: Int64(s)
        default: nil
        }
    }

    /// `message.date`: nanoseconds since 2001-01-01 on every recent macOS, seconds on an old database.
    static func date(_ raw: Int64) -> Date? {
        guard raw > 0 else { return nil }
        let seconds = raw > 100_000_000_000 ? Double(raw) / 1_000_000_000 : Double(raw)
        return Date(timeIntervalSinceReferenceDate: seconds)
    }

    static func service(_ raw: String?) -> String {
        switch raw {
        case "SMS": "SMS"
        case "RCS": "RCS"
        default: "iMessage"
        }
    }
}
