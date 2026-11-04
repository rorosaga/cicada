import CryptoKit
import Foundation
import Observation
import SQLite3

/// G39 — the columns the app may read from Apple Books' two stores, named once. `apple_books.py` re-applies the same
/// filters to whatever arrives; `AppleBooksReaderTests` proves nothing else is read.
enum AppleBooksColumns {
    static let library = ["ZASSETID", "ZTITLE", "ZAUTHOR", "ZEPUBID", "ZCONTENTTYPE", "ZISFINISHED", "ZDATEFINISHED",
                          "ZREADINGPROGRESS", "ZLASTOPENDATE", "ZCREATIONDATE", "ZISHIDDEN"]
    static let annotations = ["ZANNOTATIONASSETID", "ZANNOTATIONUUID", "ZANNOTATIONTYPE", "ZANNOTATIONSELECTEDTEXT",
                              "ZANNOTATIONNOTE", "ZANNOTATIONDELETED", "ZANNOTATIONCREATIONDATE"]
    /// `ZANNOTATIONTYPE` 2 is a highlight (with or without a note); a bookmark (1) and the reading position (3) are
    /// never read.
    static let highlightType = 2
}

/// Where Apple Books keeps its library and annotations (read on macOS 27.2, 2026-11-04): two Core Data SQLite files in
/// its sandbox, each with a version in its name, so they are found by prefix, never a hard-coded file name.
enum AppleBooksPaths {
    /// `NSHomeDirectory()`, which honours `CFFIXED_USER_HOME` (a scratch home in a verify run never reaches the real
    /// container); for the app it is the person's own home.
    static func documents(home: URL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)) -> URL {
        home.appendingPathComponent("Library/Containers/com.apple.iBooksX/Data/Documents", isDirectory: true)
    }

    static func store(in folder: URL, prefix: String) -> URL? {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? []
        return names.filter { $0.hasPrefix(prefix) && $0.hasSuffix(".sqlite") }.sorted().last
            .map { folder.appendingPathComponent($0) }
    }

    static func library(in documents: URL) -> URL? {
        store(in: documents.appendingPathComponent("BKLibrary", isDirectory: true), prefix: "BKLibrary-")
    }

    static func annotations(in documents: URL) -> URL? {
        store(in: documents.appendingPathComponent("AEAnnotation", isDirectory: true), prefix: "AEAnnotation_")
    }
}

/// One book as the backend's `POST /sources/apple-books/sync` takes it (camelCase on the wire).
struct AppleBooksBookRecord: Codable, Equatable, Sendable {
    var assetId: String
    var title: String?
    var author: String?
    var epubId: String?
    var contentType: Int?
    var isFinished: Bool
    var isHidden: Bool
    var progress: Double?
    var finishedAt: String?
    var lastOpenedAt: String?
    var addedAt: String?
    var annotations: [AppleBooksAnnotationRecord]
}

struct AppleBooksAnnotationRecord: Codable, Equatable, Sendable {
    var uuid: String?
    var createdAt: String?
    var selectedText: String?
    var note: String?
}

struct AppleBooksSyncPayload: Encodable, Sendable { let books: [AppleBooksBookRecord] }

struct AppleBooksSyncResult: Decodable, Equatable, Sendable {
    let books: Int
    let created: Int
    let updated: Int
    let unchanged: Int
    let highlights: Int
    let notes: Int
}

enum AppleBooksReadError: Error, LocalizedError, Equatable {
    case notInstalled, unreadable
    var errorDescription: String? {
        switch self {
        case .notInstalled: Copy.appleBooksMissing
        case .unreadable: Copy.appleBooksUnreadable
        }
    }
}

/// The read itself, pure and off the main actor: copy each store with its `-wal` and `-shm` into a temporary folder
/// (Apple Books keeps writing; the Chrome-history rule), open the copy read-only, read the whitelisted columns, delete
/// the copy. Core Data dates are seconds since 2001-01-01.
enum AppleBooksStore {
    static func snapshot(documents: URL) throws -> [AppleBooksBookRecord] {
        guard let library = AppleBooksPaths.library(in: documents) else { throw AppleBooksReadError.notInstalled }
        let scratch = FileManager.default.temporaryDirectory
            .appendingPathComponent("cicada-apple-books-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: scratch) }
        func copy(_ url: URL) throws -> URL {
            let target = scratch.appendingPathComponent(url.lastPathComponent)
            do { try FileManager.default.copyItem(at: url, to: target) } catch { throw AppleBooksReadError.unreadable }
            for suffix in ["-wal", "-shm"] {
                let side = URL(fileURLWithPath: url.path + suffix)
                if FileManager.default.fileExists(atPath: side.path) {
                    try? FileManager.default.copyItem(at: side, to: URL(fileURLWithPath: target.path + suffix))
                }
            }
            settle(target)
            return target
        }
        let libraryCopy = try copy(library)
        let annotationCopy = try AppleBooksPaths.annotations(in: documents).map(copy)
        return try read(library: libraryCopy, annotations: annotationCopy)
    }

    /// Fold the copied WAL into the copy and leave it a plain rollback-journal file, so the read-only open needs no
    /// `-shm` (a WAL-mode file with none cannot be opened read-only). Only ever the copy in our temporary folder.
    static func settle(_ copy: URL) {
        var db: OpaquePointer?
        guard sqlite3_open_v2(copy.path, &db, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK else { sqlite3_close(db); return }
        sqlite3_exec(db, "PRAGMA wal_checkpoint(TRUNCATE); PRAGMA journal_mode=DELETE;", nil, nil, nil)
        sqlite3_close(db)
    }

    static func read(library: URL, annotations: URL?) throws -> [AppleBooksBookRecord] {
        let db = try SQLiteReadOnly(url: library)
        defer { db.close() }
        let cols = db.columns(of: "ZBKLIBRARYASSET", whitelist: AppleBooksColumns.library)
        guard cols.contains("ZASSETID") else { throw AppleBooksReadError.unreadable }
        let rows = try db.query("SELECT \(cols.joined(separator: ", ")) FROM ZBKLIBRARYASSET", binds: [])
        var notes: [String: [AppleBooksAnnotationRecord]] = [:]
        if let annotations {
            let adb = try SQLiteReadOnly(url: annotations)
            defer { adb.close() }
            let acols = adb.columns(of: "ZAEANNOTATION", whitelist: AppleBooksColumns.annotations)
            if acols.contains("ZANNOTATIONASSETID"), acols.contains("ZANNOTATIONTYPE") {
                let deleted = acols.contains("ZANNOTATIONDELETED") ? " AND IFNULL(ZANNOTATIONDELETED, 0) = 0" : ""
                let sql = "SELECT \(acols.joined(separator: ", ")) FROM ZAEANNOTATION WHERE ZANNOTATIONTYPE = ?1"
                    + deleted
                for row in try adb.query(sql, binds: [.int(Int64(AppleBooksColumns.highlightType))]) {
                    guard let asset = row["ZANNOTATIONASSETID"] as? String else { continue }
                    let text = (row["ZANNOTATIONSELECTEDTEXT"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
                    let note = (row["ZANNOTATIONNOTE"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !(text ?? "").isEmpty || !(note ?? "").isEmpty else { continue }
                    notes[asset, default: []].append(AppleBooksAnnotationRecord(
                        uuid: row["ZANNOTATIONUUID"] as? String, createdAt: iso(row["ZANNOTATIONCREATIONDATE"]),
                        selectedText: text, note: note))
                }
            }
        }
        return rows.compactMap { row in
            guard let asset = row["ZASSETID"] as? String, !asset.isEmpty else { return nil }
            return AppleBooksBookRecord(
                assetId: asset, title: row["ZTITLE"] as? String, author: row["ZAUTHOR"] as? String,
                epubId: row["ZEPUBID"] as? String, contentType: (row["ZCONTENTTYPE"] as? NSNumber)?.intValue,
                isFinished: ((row["ZISFINISHED"] as? NSNumber)?.intValue ?? 0) != 0,
                isHidden: ((row["ZISHIDDEN"] as? NSNumber)?.intValue ?? 0) != 0,
                progress: (row["ZREADINGPROGRESS"] as? NSNumber)?.doubleValue,
                finishedAt: iso(row["ZDATEFINISHED"]), lastOpenedAt: iso(row["ZLASTOPENDATE"]),
                addedAt: iso(row["ZCREATIONDATE"]),
                annotations: (notes[asset] ?? []).sorted { ($0.createdAt ?? "", $0.uuid ?? "") < ($1.createdAt ?? "", $1.uuid ?? "") })
        }
    }

    static func iso(_ value: Any?) -> String? {
        guard let seconds = (value as? NSNumber)?.doubleValue, seconds > 0 else { return nil }
        return ISO8601DateFormatter().string(from: Date(timeIntervalSinceReferenceDate: seconds))
    }

    /// What decides whether a book is sent again: its status (never the progress figure, which moves with every page
    /// turned), its dates and its highlights. Unchanged books are not posted (an incremental re-sync).
    static func fingerprint(_ book: AppleBooksBookRecord) -> String {
        var copy = book
        copy.progress = (book.progress ?? 0) > 0 ? 1 : 0
        copy.lastOpenedAt = (book.progress ?? 0) > 0 && !book.isFinished ? nil : book.lastOpenedAt
        let data = (try? JSONEncoder.sorted.encode(copy)) ?? Data()
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined().prefix(16).description
    }

    /// The books whose fingerprint differs from the last one this memory accepted.
    static func changed(_ books: [AppleBooksBookRecord], sent: [String: String]) -> [AppleBooksBookRecord] {
        books.filter { sent[$0.assetId] != fingerprint($0) }
    }
}

private extension JSONEncoder {
    static var sorted: JSONEncoder {
        let e = JSONEncoder()
        e.outputFormatting = [.sortedKeys]
        return e
    }
}

protocol AppleBooksSyncAPI: Sendable {
    func saveAppleBooksSettings(enabled: Bool) async throws
    func syncAppleBooks(_ payload: AppleBooksSyncPayload) async throws -> AppleBooksSyncResult
}

/// G39 — Apple Books, read by the APP after the person turns it on, posted to the backend, which parses it; one way.
/// macOS asks once whether Cicada may read another app's data (the prompt comes with the first read, never before the
/// person's click). Then on launch, every few hours while Cicada runs, after a bank switch, and on Sync now. Only books
/// that changed since this memory last accepted them are posted. Turn off stops all of it and deletes nothing.
@MainActor
@Observable
final class AppleBooksReader {
    enum Status: Equatable {
        case off
        case syncing
        case synced(at: Date, books: Int, highlights: Int)
        case failed(String)
    }

    nonisolated static let channel = "apple-books"
    nonisolated static let enabledKey = "cicada.appleBooks.enabled"
    nonisolated static let sentKey = "cicada.appleBooks.sent"
    static let shared = AppleBooksReader()

    private(set) var status: Status = .off
    private(set) var enabled: Bool

    @ObservationIgnored private let api: AppleBooksSyncAPI
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let documents: URL
    @ObservationIgnored private let bank: () -> String
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let period: Duration
    @ObservationIgnored private var periodic: Task<Void, Never>?
    @ObservationIgnored private var inFlight = false
    @ObservationIgnored private var generation = 0

    init(api: AppleBooksSyncAPI = APIClient.shared, defaults: UserDefaults = .standard,
         documents: URL = AppleBooksPaths.documents(), bank: @escaping () -> String = { BankScope.value(method: "POST") ?? "default" },
         now: @escaping () -> Date = Date.init, period: Duration = .seconds(3 * 60 * 60)) {
        self.api = api; self.defaults = defaults; self.documents = documents; self.bank = bank; self.now = now
        self.period = period
        enabled = defaults.bool(forKey: Self.enabledKey)
    }

    var isInstalled: Bool { AppleBooksPaths.library(in: documents) != nil || FileManager.default.fileExists(
        atPath: documents.path) }

    func start() {
        guard enabled else { status = .off; return }
        arm()
        Task { await sync() }
    }

    func turnOn() async {
        let gen = generation
        do { try await api.saveAppleBooksSettings(enabled: true) } catch {
            guard gen == generation else { return }
            status = .failed(Self.failureMessage(error))
            return
        }
        guard gen == generation else { return }
        enabled = true
        defaults.set(true, forKey: Self.enabledKey)
        arm()
        await sync()
    }

    func turnOff() async {
        generation += 1
        enabled = false
        defaults.set(false, forKey: Self.enabledKey)
        periodic?.cancel(); periodic = nil
        status = .off
        try? await api.saveAppleBooksSettings(enabled: false)
    }

    func syncNow() async { guard enabled else { return }; await sync(resend: false) }

    /// A bank switch: the new memory has not seen these books.
    func bankChanged() async { await syncNow() }

    private func arm() {
        guard periodic == nil else { return }
        periodic = Task { [weak self, period] in
            while !Task.isCancelled {
                try? await Task.sleep(for: period)
                guard !Task.isCancelled else { return }
                await self?.syncNow()
            }
        }
    }

    private func sentKey() -> String { Self.sentKey + "." + bank() }

    private func sync(resend: Bool = false) async {
        guard !inFlight, enabled else { return }
        inFlight = true
        defer { inFlight = false }
        let gen = generation
        status = .syncing
        let documents = self.documents
        let read = await Task.detached(priority: .utility) { () -> Result<[AppleBooksBookRecord], Error> in
            Result { try AppleBooksStore.snapshot(documents: documents) }
        }.value
        guard gen == generation, enabled else { return }
        let books: [AppleBooksBookRecord]
        switch read {
        case .success(let all): books = all
        case .failure(let error):
            status = .failed((error as? LocalizedError)?.errorDescription ?? Copy.appleBooksUnreadable)
            return
        }
        var sent = (defaults.dictionary(forKey: sentKey()) as? [String: String]) ?? [:]
        let changed = resend ? books : AppleBooksStore.changed(books, sent: sent)
        var highlights = 0
        do {
            for start in stride(from: 0, to: changed.count, by: 500) {
                let chunk = Array(changed[start..<min(start + 500, changed.count)])
                let result = try await api.syncAppleBooks(AppleBooksSyncPayload(books: chunk))
                guard gen == generation else { return }
                highlights += result.highlights
                for book in chunk { sent[book.assetId] = AppleBooksStore.fingerprint(book) }
                defaults.set(sent, forKey: sentKey())
            }
        } catch {
            guard gen == generation else { return }
            status = .failed(Self.failureMessage(error))
            return
        }
        let total = books.reduce(0) { $0 + $1.annotations.filter { !($0.selectedText ?? "").isEmpty }.count }
        status = .synced(at: now(), books: books.filter { !$0.isHidden }.count, highlights: max(total, highlights))
    }

    static func failureMessage(_ error: Error) -> String {
        if error is URLError { return Copy.calendarBackendDown }
        guard let api = error as? APIError else { return Copy.appleBooksSyncFailed }
        switch api {
        case .httpError(409, let body): return ProjectWriteFailure.detail(body) ?? Copy.appleBooksSyncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.appleBooksNeedsUpdate
        case .serverUnreachable: return Copy.calendarBackendDown
        default: return Copy.appleBooksSyncFailed
        }
    }
}
