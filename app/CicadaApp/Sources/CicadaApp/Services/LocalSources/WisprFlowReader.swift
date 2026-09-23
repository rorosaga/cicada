import Foundation
import SQLite3

/// G134 — the columns the app may read from Wispr Flow's database, and the ones
/// it must never read, named once (R-N1, R-LS21). `wispr_flow.py` holds the
/// same lists; `WisprFlowReaderTests` proves `forbidden` is disjoint from every
/// whitelist and absent from every payload.
enum WisprFlowColumns {
    static let meetings = ["id", "title", "createdAt", "modifiedAt", "endedAt", "isDeleted", "finalized",
                           "isTourDemo", "transcriptDeletedAt", "participantNames", "speakerMap", "notes", "summary"]
    static let notes = ["id", "title", "content", "createdAt", "modifiedAt", "isDeleted"]
    static let todos = ["meetingId", "title", "status", "isDeleted"]
    static let history = ["timestamp", "formattedText", "editedText", "app", "numWords"]
    static let forbidden = ["audio", "builtInAudio", "screenshot", "axText", "axHTML", "textboxContents",
                            "pastedText", "url", "asrText"]
}

/// A cursor column's raw value, bound back as the same SQLite type — Wispr
/// Flow's timestamp columns may be ISO text or epoch numbers, and `>` only
/// compares meaningfully within one type.
enum SQLiteCursor: Codable, Equatable, Sendable {
    case int(Int64), real(Double), text(String)

    init?(any value: Any?) {
        if let number = value as? NSNumber {
            if CFNumberIsFloatType(number as CFNumber) { self = .real(number.doubleValue) } else { self = .int(number.int64Value) }
        } else if let text = value as? String {
            self = .text(text)
        } else {
            return nil
        }
    }
}

struct WisprFlowCursor: Codable, Equatable, Sendable {
    var meetings: SQLiteCursor?
    var notes: SQLiteCursor?
    var history: SQLiteCursor?
}

enum SQLiteReadError: Error, LocalizedError {
    case open(String), query(String)
    var errorDescription: String? {
        switch self {
        case .open(let m): "Couldn't open Wispr Flow's data: \(m)"
        case .query(let m): "Couldn't read Wispr Flow's data: \(m)"
        }
    }
}

/// A read-only connection to someone else's database (R-N1): `mode=ro` through
/// a URI — never `immutable`, which would read past a live WAL — a 2 s busy
/// timeout, and the caller wraps one pass in a single read transaction so the
/// projection is a consistent snapshot while Wispr Flow keeps writing.
final class SQLiteReadOnly {
    private var db: OpaquePointer?
    private static let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    init(url: URL) throws {
        let encoded = url.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? url.path
        let rc = sqlite3_open_v2("file:\(encoded)?mode=ro", &db,
                                 SQLITE_OPEN_READONLY | SQLITE_OPEN_URI | SQLITE_OPEN_NOMUTEX, nil)
        guard rc == SQLITE_OK else {
            let message = db.flatMap { sqlite3_errmsg($0) }.map { String(cString: $0) } ?? "code \(rc)"
            sqlite3_close(db)
            db = nil
            throw SQLiteReadError.open(message)
        }
        sqlite3_busy_timeout(db, 2000)
    }

    func close() {
        if let db { sqlite3_close(db) }
        db = nil
    }

    deinit { close() }

    private var lastError: String { sqlite3_errmsg(db).map { String(cString: $0) } ?? "unknown error" }

    func exec(_ sql: String) throws {
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else { throw SQLiteReadError.query(lastError) }
    }

    /// The whitelisted columns this table actually has, in whitelist order —
    /// never `SELECT *`, so a column Wispr Flow adds tomorrow is not read (R-LS21).
    func columns(of table: String, whitelist: [String]) -> [String] {
        guard let rows = try? query("PRAGMA table_info(\(table))", bind: nil) else { return [] }
        let present = Set(rows.compactMap { $0["name"] as? String })
        return whitelist.filter(present.contains)
    }

    func query(_ sql: String, bind cursor: SQLiteCursor?) throws -> [[String: Any]] {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { throw SQLiteReadError.query(lastError) }
        defer { sqlite3_finalize(stmt) }
        if sql.contains("?1") {
            switch cursor {
            case .int(let v): sqlite3_bind_int64(stmt, 1, v)
            case .real(let v): sqlite3_bind_double(stmt, 1, v)
            case .text(let v): sqlite3_bind_text(stmt, 1, v, -1, Self.transient)
            case nil: sqlite3_bind_null(stmt, 1)
            }
        }
        var rows: [[String: Any]] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            var row: [String: Any] = [:]
            for i in 0..<sqlite3_column_count(stmt) {
                guard let name = sqlite3_column_name(stmt, i).map({ String(cString: $0) }) else { continue }
                switch sqlite3_column_type(stmt, i) {
                case SQLITE_INTEGER: row[name] = NSNumber(value: sqlite3_column_int64(stmt, i))
                case SQLITE_FLOAT: row[name] = NSNumber(value: sqlite3_column_double(stmt, i))
                case SQLITE_TEXT: row[name] = sqlite3_column_text(stmt, i).map { String(cString: $0) } ?? ""
                case SQLITE_NULL: row[name] = NSNull()
                default: continue  // a BLOB is never projected, whatever column holds it (R-LS21)
                }
            }
            rows.append(row)
        }
        return rows
    }
}

/// One pass over Wispr Flow's store, ready to post. Built and serialised off
/// the main actor; only `Sendable` values leave the task.
struct WisprFlowPass: Sendable {
    var json: Data
    var cursor: WisprFlowCursor
    var isEmpty: Bool
    var hasMore: Bool
}

/// G134 — reads Wispr Flow's local store the way R-N1 allows: the APP opens it
/// (the launchd backend has no Full Disk Access and never touches `~/Library`),
/// read-only, projecting only whitelisted columns of finalized, non-deleted,
/// non-demo meetings, Scratchpad notes, their to-dos, and — only when the
/// person opted in — dictation history. Audio, screenshots, accessibility text,
/// pasted text and URLs never leave the file (R-LS21). Incremental: each table
/// is read past a cursor on its own modification column, `batchLimit` rows at a
/// time.
struct WisprFlowReader: Sendable {
    let root: URL
    var batchLimit = 150
    var historyLimit = 5000
    /// A `refined.ndjson` larger than this is not read (a runaway file, not a meeting).
    var maxTranscriptBytes = 20_000_000

    static var standardRoot: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Wispr Flow", isDirectory: true)
    }

    var database: URL { root.appendingPathComponent("flow.sqlite") }

    func read(since cursor: WisprFlowCursor, includeDictation: Bool) throws -> WisprFlowPass {
        // Permission first, with the exact fix (R9): opening the file classifies
        // EPERM as `.notReadable` (Full Disk Access) and ENOENT as `.missing`.
        do {
            let handle = try FileHandle(forReadingFrom: database)
            try handle.close()
        } catch {
            // `FileHandle` reports an absent file as Cocoa code 4 (NSFileNoSuchFileError),
            // which `BrowserFileError.classify` (written for `Data(contentsOf:)`'s 260)
            // would call a permission problem — and send the person to a setting
            // that fixes nothing.
            let ns = error as NSError
            if ns.domain == NSCocoaErrorDomain && ns.code == NSFileNoSuchFileError {
                throw BrowserFileError.missing(.wisprFlowDatabase, [database.path])
            }
            throw BrowserFileError.classify(error, file: .wisprFlowDatabase, path: database.path)
        }
        let db = try SQLiteReadOnly(url: database)
        defer { db.close() }
        try db.exec("BEGIN")
        defer { try? db.exec("COMMIT") }

        var next = cursor
        var meetings: [[String: Any]] = []
        var notes: [[String: Any]] = []
        var todos: [[String: Any]] = []
        var history: [[String: Any]]? = nil
        var deletedMeetings: [String] = []
        var deletedNotes: [String] = []
        var hasMore = false

        let mcols = db.columns(of: "Meetings", whitelist: WisprFlowColumns.meetings)
        if mcols.contains("id") && mcols.contains("modifiedAt") {
            var filters = ["(?1 IS NULL OR modifiedAt > ?1)"]
            if mcols.contains("isDeleted") { filters.append("COALESCE(isDeleted, 0) = 0") }
            if mcols.contains("isTourDemo") { filters.append("COALESCE(isTourDemo, 0) = 0") }
            if mcols.contains("finalized") { filters.append("COALESCE(finalized, 0) = 1") }
            let rows = try db.query("SELECT \(mcols.joined(separator: ", ")) FROM Meetings WHERE "
                                    + filters.joined(separator: " AND ") + " ORDER BY modifiedAt LIMIT \(batchLimit)",
                                    bind: cursor.meetings)
            hasMore = hasMore || rows.count == batchLimit
            for row in rows {
                meetings.append(["row": row, "utterances": utterances(meetingId: Self.text(row["id"]))])
            }
            if let last = SQLiteCursor(any: rows.last?["modifiedAt"]) { next.meetings = last }
            if cursor.meetings != nil, mcols.contains("isDeleted") {
                deletedMeetings = try db.query("SELECT id FROM Meetings WHERE isDeleted = 1 AND modifiedAt > ?1",
                                               bind: cursor.meetings).map { Self.text($0["id"]) }
            }
            let tcols = db.columns(of: "Todos", whitelist: WisprFlowColumns.todos)
            let ids = Set(meetings.compactMap { ($0["row"] as? [String: Any]).map { Self.text($0["id"]) } })
            if tcols.contains("meetingId"), !ids.isEmpty {
                todos = try db.query("SELECT \(tcols.joined(separator: ", ")) FROM Todos", bind: nil)
                    .filter { ids.contains(Self.text($0["meetingId"])) }
            }
        }

        let ncols = db.columns(of: "Notes", whitelist: WisprFlowColumns.notes)
        if ncols.contains("id") && ncols.contains("modifiedAt") {
            var filters = ["(?1 IS NULL OR modifiedAt > ?1)"]
            if ncols.contains("isDeleted") { filters.append("COALESCE(isDeleted, 0) = 0") }
            notes = try db.query("SELECT \(ncols.joined(separator: ", ")) FROM Notes WHERE "
                                 + filters.joined(separator: " AND ") + " ORDER BY modifiedAt LIMIT \(batchLimit)",
                                 bind: cursor.notes)
            hasMore = hasMore || notes.count == batchLimit
            if let last = SQLiteCursor(any: notes.last?["modifiedAt"]) { next.notes = last }
            if cursor.notes != nil, ncols.contains("isDeleted") {
                deletedNotes = try db.query("SELECT id FROM Notes WHERE isDeleted = 1 AND modifiedAt > ?1",
                                            bind: cursor.notes).map { Self.text($0["id"]) }
            }
        }

        if includeDictation {
            let hcols = db.columns(of: "History", whitelist: WisprFlowColumns.history)
            if hcols.contains("timestamp") {
                let rows = try db.query("SELECT \(hcols.joined(separator: ", ")) FROM History WHERE "
                                        + "(?1 IS NULL OR timestamp > ?1) ORDER BY timestamp LIMIT \(historyLimit)",
                                        bind: cursor.history)
                history = rows
                hasMore = hasMore || rows.count == historyLimit
                if let last = SQLiteCursor(any: rows.last?["timestamp"]) { next.history = last }
            }
        }

        var body: [String: Any] = ["meetings": meetings, "notes": notes, "todos": todos,
                                   "deletedMeetingIds": deletedMeetings, "deletedNoteIds": deletedNotes]
        if let history { body["history"] = history }
        let isEmpty = meetings.isEmpty && notes.isEmpty && (history ?? []).isEmpty
            && deletedMeetings.isEmpty && deletedNotes.isEmpty
        return WisprFlowPass(json: try JSONSerialization.data(withJSONObject: body), cursor: next,
                             isEmpty: isEmpty, hasMore: hasMore)
    }

    /// A meeting's diarized utterances, projected to `timestamp`, `text` and
    /// `speaker{id, name, source}` — nothing else in the line crosses (R-LS21).
    func utterances(meetingId: String) -> [[String: Any]] {
        let safe = meetingId.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
        guard !safe.isEmpty, safe == meetingId else { return [] }
        let file = root.appendingPathComponent("meetings/\(safe)/refined.ndjson")
        guard let size = (try? FileManager.default.attributesOfItem(atPath: file.path))?[.size] as? NSNumber,
              size.intValue <= maxTranscriptBytes,
              let text = try? String(contentsOf: file, encoding: .utf8) else { return [] }
        return text.split(separator: "\n").compactMap { line -> [String: Any]? in
            guard let object = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else { return nil }
            var out: [String: Any] = [:]
            if let ts = object["timestamp"], !(ts is NSNull) { out["timestamp"] = ts }
            if let words = object["text"] as? String { out["text"] = words }
            if let speaker = object["speaker"] as? [String: Any] {
                var kept: [String: Any] = [:]
                for key in ["id", "name", "source"] {
                    if let value = speaker[key], !(value is NSNull) { kept[key] = value }
                }
                out["speaker"] = kept
            }
            return out["text"] == nil ? nil : out
        }
    }

    private static func text(_ value: Any?) -> String {
        switch value {
        case let s as String: s
        case let n as NSNumber: n.stringValue
        default: ""
        }
    }
}
