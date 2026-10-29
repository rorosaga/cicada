import SQLite3
import XCTest
@testable import CicadaApp

/// G179 — a synthetic `chat.db` for the Messages tests: the real table structure (the same
/// `api/tests/fixtures/chatdb_tables.sql` the backend's tests build from), placeholder handles and words, and
/// `attributedBody` blobs archived the way Messages archives them.
final class SyntheticChatDB {
    let dir: URL
    var url: URL { dir.appendingPathComponent("chat.db") }
    private var db: OpaquePointer?
    private static let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
    private var guidCounter = 0

    static var schemaURL: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("api/tests/fixtures/chatdb_tables.sql")
    }

    init() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("SyntheticChatDB-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        XCTAssertEqual(sqlite3_open(url.path, &db), SQLITE_OK)
        let schema = try String(contentsOf: Self.schemaURL, encoding: .utf8)
        XCTAssertEqual(sqlite3_exec(db, schema, nil, nil, nil), SQLITE_OK)
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
            case let v as String: sqlite3_bind_text(stmt, at, v, -1, Self.transient)
            case let v as Data: _ = v.withUnsafeBytes { sqlite3_bind_blob(stmt, at, $0.baseAddress, Int32(v.count), Self.transient) }
            default: sqlite3_bind_null(stmt, at)
            }
        }
        XCTAssertEqual(sqlite3_step(stmt), SQLITE_DONE, String(cString: sqlite3_errmsg(db)))
    }

    var lastRow: Int64 { sqlite3_last_insert_rowid(db) }

    @discardableResult
    func chat(_ handle: String, style: Int = 45, name: String = "") -> Int64 {
        exec("INSERT INTO handle (id, service) VALUES (?, 'iMessage')", [handle])
        let h = lastRow
        exec("INSERT INTO chat (guid, style, chat_identifier, service_name, display_name) VALUES (?, ?, ?, 'iMessage', ?)",
             ["iMessage;\(style == 45 ? "-" : "+");\(handle)", style, handle, name])
        let c = lastRow
        exec("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)", [c, h])
        return c
    }

    /// A group chat (`style` 43) with these members' handles.
    @discardableResult
    func group(_ handles: [String], name: String = "") -> Int64 {
        exec("INSERT INTO chat (guid, style, chat_identifier, service_name, display_name) VALUES (?, 43, ?, 'iMessage', ?)",
             ["iMessage;+;chat\(handles.count)\(guidCounter)", "chat\(handles.count)\(guidCounter)", name])
        let c = lastRow
        for handle in handles {
            exec("INSERT INTO handle (id, service) VALUES (?, 'iMessage')", [handle])
            exec("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)", [c, lastRow])
        }
        return c
    }

    /// A member's row in a group: the message's `handle_id` is that member's handle.
    @discardableResult
    func message(_ chat: Int64, minute: Int, from handle: String, text: String) -> Int64 {
        let m = message(chat, minute: minute, fromMe: false, text: text)
        exec("UPDATE message SET handle_id = (SELECT ROWID FROM handle WHERE id = ? ORDER BY ROWID DESC LIMIT 1) "
             + "WHERE ROWID = ?", [handle, m])
        return m
    }

    /// `NSArchiver` of an `NSMutableAttributedString` — how Messages keeps a message's words in `attributedBody`.
    static func archived(_ text: String) -> Data {
        let string = NSMutableAttributedString(string: text)
        string.addAttribute(NSAttributedString.Key("__kIMMessagePartAttributeName"), value: NSNumber(value: 0),
                            range: NSRange(location: 0, length: (text as NSString).length))
        return NSArchiver.archivedData(withRootObject: string)
    }

    @discardableResult
    func message(_ chat: Int64, minute: Int, fromMe: Bool, text: String?, bodyOnly: Bool = false,
                 tapback: Bool = false, attachment: String? = nil) -> Int64 {
        guidCounter += 1
        let date = Int64(minute) * 60 * 1_000_000_000 + 800_000_000_000_000_000
        exec("""
            INSERT INTO message (guid, text, attributedBody, date, is_from_me, associated_message_type, cache_has_attachments)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ["SYNTH-\(guidCounter)", bodyOnly ? nil : text, text.map(Self.archived), date, fromMe ? 1 : 0,
                  tapback ? 2000 : 0, attachment == nil ? 0 : 1])
        let m = lastRow
        exec("INSERT INTO chat_message_join (chat_id, message_id, message_date) VALUES (?, ?, ?)", [chat, m, date])
        if let attachment {
            exec("INSERT INTO attachment (guid, original_guid, filename, mime_type, uti, transfer_name, total_bytes) "
                 + "VALUES (?, ?, ?, 'image/png', 'public.png', ?, 10)",
                 ["A\(m)", "A\(m)", "~/Library/Messages/Attachments/CANARY-path/\(attachment)", attachment])
            exec("INSERT INTO message_attachment_join (message_id, attachment_id) VALUES (?, ?)", [m, lastRow])
        }
        return m
    }
}
