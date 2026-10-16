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
/// **What it reads.** For the list: each one-to-one chat's id, its handle (to find the contact's name and photo on
/// this Mac — never sent), its own display name, the last message's time and how many messages each side sent. Group
/// chats (`chat.style` 43) are left out of this slice. For a TICKED chat only: each message row's id, guid, time,
/// direction, `text` and `attributedBody` (the archived words, sent as base64 for the backend to decode), its
/// reaction/event columns, its edit and unsend times, and its attachments' *names* and types — never
/// `attachment.filename` (a path) and never an attachment's bytes. No other column, no other chat.
///
/// **Which chats.** The Settings list is the `listLimit` most recent chats; a ticked chat is read by its own id
/// (`conversations(ids:)`), whatever its rank, so a quiet chat that falls below the list's cap never stops syncing.
///
/// **Cursor.** Past `message.ROWID`, plus rows edited or unsent after the newest edit time already seen (an edit keeps
/// its old ROWID), `batchLimit` rows at a time.
struct MessagesReader: Sendable {
    let database: URL
    var batchLimit = 500
    var listLimit = 200

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
               COALESCE(c.service_name, '') AS service,
               (SELECT MAX(j.message_date) FROM chat_message_join j WHERE j.chat_id = c.ROWID) AS last,
               (SELECT COUNT(*) FROM chat_message_join j JOIN message m ON m.ROWID = j.message_id
                 WHERE j.chat_id = c.ROWID AND m.is_from_me = 1 AND COALESCE(m.associated_message_type, 0) = 0
                   AND COALESCE(m.item_type, 0) = 0) AS from_me,
               (SELECT COUNT(*) FROM chat_message_join j JOIN message m ON m.ROWID = j.message_id
                 WHERE j.chat_id = c.ROWID AND m.is_from_me = 0 AND COALESCE(m.associated_message_type, 0) = 0
                   AND COALESCE(m.item_type, 0) = 0) AS from_them
        FROM chat c
        WHERE COALESCE(c.style, 45) = 45
        """
    static let conversationsSQL = conversationsSelect + " ORDER BY last DESC"

    /// Every one-to-one conversation, most recent first, at most `listLimit` — the Settings picker's list only.
    func conversations() throws -> [MessagesConversation] {
        let db = try open()
        defer { db.close() }
        let rows: [[String: Any]]
        do {
            try db.exec("BEGIN")
            defer { try? db.exec("COMMIT") }
            rows = try db.query(Self.conversationsSQL + " LIMIT \(listLimit)", binds: [])
        } catch {
            throw MessagesReadError.unreadable(String(describing: error))
        }
        return rows.compactMap(Self.conversation)
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
            let chats = try db.query("SELECT ROWID AS chat, guid FROM chat WHERE COALESCE(style, 45) = 45", binds: [])
            let wanted = chats.compactMap { row -> Int64? in
                guard let chat = Self.int(row["chat"]), let guid = row["guid"] as? String, !guid.isEmpty,
                      ids.contains(Self.conversationId(chatGuid: guid)) else { return nil }
                return chat
            }
            guard !wanted.isEmpty else { return [] }
            let marks = Array(repeating: "?", count: wanted.count).joined(separator: ", ")
            rows = try db.query(Self.conversationsSelect + " AND c.ROWID IN (\(marks)) ORDER BY last DESC",
                                binds: wanted.map { .int($0) })
        } catch {
            throw MessagesReadError.unreadable(String(describing: error))
        }
        return rows.compactMap(Self.conversation)
    }

    private static func conversation(_ row: [String: Any]) -> MessagesConversation? {
        guard let chat = int(row["chat"]), let guid = row["guid"] as? String, !guid.isEmpty else { return nil }
        let fromMe = Int(int(row["from_me"]) ?? 0), fromThem = Int(int(row["from_them"]) ?? 0)
        guard fromMe + fromThem > 0 else { return nil }
        return MessagesConversation(
            id: conversationId(chatGuid: guid), chatRowId: chat, handle: (row["handle"] as? String) ?? "",
            displayName: (row["name"] as? String) ?? "", service: service(row["service"] as? String),
            lastActivity: int(row["last"]).flatMap(date), fromMe: fromMe, fromThem: fromThem)
    }

    static let rowsSQL = """
        SELECT m.ROWID AS rowid, m.guid AS guid, m.date AS date, m.is_from_me AS is_from_me, m.text AS text,
               m.attributedBody AS attributed_body,
               COALESCE(m.associated_message_type, 0) AS associated_message_type, COALESCE(m.item_type, 0) AS item_type,
               COALESCE(m.is_system_message, 0) AS is_system_message, COALESCE(m.date_edited, 0) AS date_edited,
               COALESCE(m.date_retracted, 0) AS date_retracted
        FROM message m JOIN chat_message_join j ON j.message_id = m.ROWID
        WHERE j.chat_id = ?1
          AND (m.ROWID > ?2 OR COALESCE(m.date_edited, 0) > ?3 OR COALESCE(m.date_retracted, 0) > ?3)
        ORDER BY m.ROWID
        """

    /// One batch of a ticked conversation's rows past `cursor`, serialised as the sync request.
    func read(_ conversation: MessagesConversation, name: String, since cursor: MessagesCursor) throws -> MessagesPass {
        let db = try open()
        defer { db.close() }
        var rows: [[String: Any]] = []
        var attachments: [Int64: [[String: Any]]] = [:]
        do {
            try db.exec("BEGIN")
            defer { try? db.exec("COMMIT") }
            rows = try db.query(Self.rowsSQL + " LIMIT \(batchLimit)",
                                binds: [.int(conversation.chatRowId), .int(cursor.rowid), .int(cursor.changed)],
                                base64Blobs: ["attributed_body"])
            let ids = rows.compactMap { Self.int($0["rowid"]) }
            if !ids.isEmpty {
                let marks = Array(repeating: "?", count: ids.count).joined(separator: ", ")
                let found = try db.query(
                    "SELECT j.message_id AS message, a.transfer_name AS name, a.mime_type AS mime, a.uti AS uti, "
                    + "COALESCE(a.total_bytes, 0) AS bytes FROM attachment a "
                    + "JOIN message_attachment_join j ON j.attachment_id = a.ROWID "
                    + "WHERE j.message_id IN (\(marks)) ORDER BY j.message_id, a.ROWID",
                    binds: ids.map { .int($0) })
                for att in found {
                    guard let message = Self.int(att["message"]) else { continue }
                    var item: [String: Any] = ["name": (att["name"] as? String) ?? "",
                                               "totalBytes": Self.int(att["bytes"]) ?? 0]
                    if let mime = att["mime"] as? String { item["mimeType"] = mime }
                    if let uti = att["uti"] as? String { item["uti"] = uti }
                    attachments[message, default: []].append(item)
                }
            }
        } catch {
            throw MessagesReadError.unreadable(String(describing: error))
        }
        var next = cursor
        var messages: [[String: Any]] = []
        for row in rows {
            guard let rowid = Self.int(row["rowid"]) else { continue }
            if rowid > next.rowid { next.rowid = rowid }
            let edited = Self.int(row["date_edited"]) ?? 0, retracted = Self.int(row["date_retracted"]) ?? 0
            next.changed = max(next.changed, edited, retracted)
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
            if let body = row["attributed_body"] as? String { message["attributedBody"] = body }
            messages.append(message)
        }
        let body: [String: Any] = [
            "conversation": ["id": conversation.id, "name": name, "displayName": conversation.displayName,
                             "service": conversation.service, "group": false,
                             "fromMe": conversation.fromMe, "fromThem": conversation.fromThem],
            "messages": messages,
        ]
        return MessagesPass(json: try JSONSerialization.data(withJSONObject: body), cursor: next,
                            count: messages.count, hasMore: rows.count == batchLimit)
    }

    // MARK: helpers

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
