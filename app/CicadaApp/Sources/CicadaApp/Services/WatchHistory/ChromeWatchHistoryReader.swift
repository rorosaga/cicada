import Foundation

/// One visit to a YouTube video page, as Chrome's History recorded it — the only thing that leaves the app.
struct WatchHistoryVisit: Codable, Equatable, Sendable {
    let url: String
    let title: String
    let visitedAt: String
}

/// `POST /sources/watch-history/sync`'s body.
struct WatchHistoryPayload: Codable, Equatable, Sendable {
    let browser: String
    let profile: String
    let visits: [WatchHistoryVisit]
}

/// `POST /sources/watch-history/sync`'s answer.
struct WatchHistorySyncResult: Codable, Equatable, Sendable {
    var received = 0
    var kept = 0
    var ignored = 0
    var added = 0
    var videos = 0
    var daysCreated = 0
    var daysUpdated = 0
    var daysUnchanged = 0
    var bank = ""
}

/// One pass over the History copy: the visits to post and where the next pass starts.
struct WatchHistoryPass: Equatable, Sendable {
    var visits: [WatchHistoryVisit]
    /// The highest visit id this pass looked at — every row the query returned, kept or not — so the next pass never
    /// re-reads a row the Swift check refused.
    var lastVisitId: Int64
    var hasMore: Bool
}

/// G71 (owner 2026-10-16) — the YouTube videos the person watched in Chrome, read from Chrome's own History database
/// on this Mac, the way the Awake rail allows: the APP reads it (the backend never opens `~/Library`), only after the
/// person turned it on, and only YouTube watch pages leave the app.
///
/// **A copy, never the live file.** Chrome holds `History` locked while it runs, so each pass copies the file (and a
/// `-wal` beside it, should Chrome ever write one) into a private folder (0700) under the temporary directory, opens
/// the COPY read-only, and deletes the folder before returning. The live file is only ever copied — never opened,
/// written or locked.
///
/// **YouTube video pages only.** The query itself names them (`visitsSQL`: `watch?` on youtube.com and its `m.` and
/// `music.` hosts, `/shorts/`, `youtu.be/`), so no other row of the history is read into memory; each row is checked
/// again here (`isWatchURL`) and again by the backend. A row's title and visit time come from the file itself —
/// nothing is fetched.
///
/// **Cursor.** Past `visits.id`, oldest first, `batchLimit` rows a pass. Ids only grow, except when the person clears
/// their history (ids may start again): a cursor above the file's highest id is reset to zero, and the backend's day
/// records make a re-read harmless.
struct ChromeWatchHistoryReader: Sendable {
    let historyFile: URL
    var batchLimit = 2000
    var scratchRoot: URL = FileManager.default.temporaryDirectory

    static var standardHistory: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Google/Chrome/Default/History")
    }

    // sql:begin — read by api/tests/test_watch_history.py, which runs it on a synthetic History database.
    static let visitsSQL = """
        SELECT v.id AS visit, u.url AS url, COALESCE(u.title, '') AS title, v.visit_time AS visit_time
        FROM visits v JOIN urls u ON u.id = v.url
        WHERE v.id > ?1
          AND (u.url LIKE 'https://www.youtube.com/watch?%' OR u.url LIKE 'https://youtube.com/watch?%'
               OR u.url LIKE 'https://m.youtube.com/watch?%' OR u.url LIKE 'https://music.youtube.com/watch?%'
               OR u.url LIKE 'https://www.youtube.com/shorts/%' OR u.url LIKE 'https://m.youtube.com/shorts/%'
               OR u.url LIKE 'https://youtube.com/shorts/%' OR u.url LIKE 'https://youtu.be/%')
        ORDER BY v.id
        LIMIT ?2
        """
    // sql:end

    static let maxVisitSQL = "SELECT COALESCE(MAX(id), 0) AS top FROM visits"

    /// Opening the file first classifies a refused read (the fix: Full Disk Access) and an absent one (Chrome not
    /// installed, or never run).
    func checkAccess() throws {
        do {
            let handle = try FileHandle(forReadingFrom: historyFile)
            try handle.close()
        } catch {
            let ns = error as NSError
            if ns.domain == NSCocoaErrorDomain && (ns.code == NSFileNoSuchFileError || ns.code == NSFileReadNoSuchFileError) {
                throw BrowserFileError.missing(.chromeHistory, [historyFile.path])
            }
            throw BrowserFileError.classify(error, file: .chromeHistory, path: historyFile.path)
        }
    }

    /// One pass past `cursor`.
    func read(after cursor: Int64) throws -> WatchHistoryPass {
        try checkAccess()
        let fm = FileManager.default
        let folder = scratchRoot.appendingPathComponent("cicada-watch-history-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        defer { try? fm.removeItem(at: folder) }
        let copy = folder.appendingPathComponent("History")
        do {
            try fm.copyItem(at: historyFile, to: copy)
            let wal = URL(fileURLWithPath: historyFile.path + "-wal")
            if fm.fileExists(atPath: wal.path) {
                try fm.copyItem(at: wal, to: URL(fileURLWithPath: copy.path + "-wal"))
            }
        } catch {
            throw BrowserFileError.classify(error, file: .chromeHistory, path: historyFile.path)
        }
        let db: SQLiteReadOnly
        do { db = try SQLiteReadOnly(url: copy) } catch { throw WatchHistoryReadError.unreadable }
        defer { db.close() }
        var start = max(0, cursor)
        let rows: [[String: Any]]
        do {
            try db.exec("BEGIN")
            defer { try? db.exec("COMMIT") }
            let top = try db.query(Self.maxVisitSQL, binds: []).first.flatMap { Self.int($0["top"]) } ?? 0
            if start > top { start = 0 }   // the person cleared their history: ids started again
            rows = try db.query(Self.visitsSQL, binds: [.int(start), .int(Int64(batchLimit))])
        } catch {
            throw WatchHistoryReadError.unreadable
        }
        var visits: [WatchHistoryVisit] = []
        var last = start
        for row in rows {
            guard let id = Self.int(row["visit"]) else { continue }
            last = max(last, id)
            guard let url = row["url"] as? String, Self.isWatchURL(url),
                  let micros = Self.int(row["visit_time"]), let at = Self.instant(webkitMicros: micros) else { continue }
            visits.append(WatchHistoryVisit(url: url, title: (row["title"] as? String) ?? "", visitedAt: at))
        }
        return WatchHistoryPass(visits: visits, lastVisitId: last, hasMore: rows.count >= batchLimit)
    }

    /// A YouTube video page: `watch?v=` on youtube.com (or its `www.`, `m.`, `music.` hosts), `/shorts/<id>`, or
    /// `youtu.be/<id>`. Anything else — another site, a search, a channel, a lookalike host — is not.
    static func isWatchURL(_ string: String) -> Bool {
        guard let parts = URLComponents(string: string), parts.scheme?.lowercased() == "https",
              let host = parts.host?.lowercased() else { return false }
        let path = parts.path
        if host == "youtu.be" { return path.count > 1 }
        guard ["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"].contains(host) else { return false }
        if path == "/watch" {
            return parts.queryItems?.contains { $0.name == "v" && !($0.value ?? "").isEmpty } ?? false
        }
        return path.hasPrefix("/shorts/") && path.count > "/shorts/".count
    }

    /// Chrome's visit time (microseconds since 1601-01-01 UTC) as an ISO 8601 instant; nil when out of range.
    static func instant(webkitMicros micros: Int64) -> String? {
        let seconds = Double(micros) / 1_000_000 - 11_644_473_600
        guard seconds > 1_104_537_600, seconds < 4_102_444_800 else { return nil }   // 2005 … 2100
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: Date(timeIntervalSince1970: seconds.rounded(.down)))
    }

    static func int(_ value: Any?) -> Int64? {
        (value as? NSNumber)?.int64Value
    }
}

enum WatchHistoryReadError: Error, LocalizedError, Equatable {
    case unreadable
    var errorDescription: String? { Copy.watchHistoryUnreadable }
}
