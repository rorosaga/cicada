import CryptoKit
import Foundation
import ImageIO
import Observation
import SQLite3
import UniformTypeIdentifiers

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

    /// An absent folder is nil (nothing here yet); a folder macOS refuses to list throws, so a denial is never read
    /// as "Open Apple Books once" (the capture rail: an unreadable file shows the exact fix).
    static func store(in folder: URL, prefix: String) throws -> URL? {
        let names: [String]
        do {
            names = try FileManager.default.contentsOfDirectory(atPath: folder.path)
        } catch {
            let refusal = BrowserFileError.classify(error, file: .appleBooksLibrary, path: folder.path)
            if case .missing = refusal { return nil }
            throw refusal
        }
        return names.filter { $0.hasPrefix(prefix) && $0.hasSuffix(".sqlite") }.sorted().last
            .map { folder.appendingPathComponent($0) }
    }

    static func library(in documents: URL) throws -> URL? {
        try store(in: documents.appendingPathComponent("BKLibrary", isDirectory: true), prefix: "BKLibrary-")
    }

    static func annotations(in documents: URL) throws -> URL? {
        try store(in: documents.appendingPathComponent("AEAnnotation", isDirectory: true), prefix: "AEAnnotation_")
    }
}

/// Ruling 61 — the cover Apple Books itself keeps of each book it has shown (read on macOS 27.2): one folder per asset
/// in its sandbox's cache, `<asset id>|<scale>|<width>|<height>|<n>.<jpg|heic|astc>`. Read by the app after the person
/// turned Apple Books on, the same container as the library; nothing leaves this Mac but the backend's own post. The
/// largest picture ImageIO can read is drawn down to a small JPEG (the `.astc` textures are not pictures it reads).
enum AppleBooksCovers {
    static let longestSide: CGFloat = 600
    static let maxBytes = 512 * 1024
    /// How many covers one sync reads; the next sync goes on from there.
    static let maxPerSync = 200
    /// `book_covers.MAX_PER_POST`.
    static let perPost = 25
    private static let readable: Set<String> = ["jpg", "jpeg", "png", "heic"]
    /// `ZCONTENTTYPE` of a PDF and an audiobook (`apple_books.py` names them): not a book's cover.
    private static let notBooks: Set<Int> = [3, 5]

    /// The assets whose cover is worth sending: books the person has not hidden.
    static func assets(of books: [AppleBooksBookRecord]) -> [String] {
        books.filter { !$0.isHidden && !notBooks.contains($0.contentType ?? 1) }.map(\.assetId)
    }

    static func folder(documents: URL) -> URL {
        documents.deletingLastPathComponent()
            .appendingPathComponent("Library/Caches/BCCoverCache-1/BICDiskDataStore", isDirectory: true)
    }

    /// An asset id names a folder only when it is one path component: never a separator, never `..`.
    static func isPathSafe(_ asset: String) -> Bool {
        !asset.isEmpty && asset.count <= 200 && !asset.contains("/") && !asset.contains("\\") && !asset.hasPrefix(".")
    }

    /// The largest readable picture of this asset, by the pixels its name states.
    static func bestFile(asset: String, in folder: URL) -> URL? {
        guard isPathSafe(asset) else { return nil }
        let own = folder.appendingPathComponent(asset, isDirectory: true)
        let names = (try? FileManager.default.contentsOfDirectory(atPath: own.path)) ?? []
        func pixels(_ name: String) -> Int {
            let parts = name.split(separator: "|")
            guard parts.count >= 4, let w = Int(parts[2]), let h = Int(parts[3]) else { return 0 }
            return w * h
        }
        return names.filter { readable.contains(($0 as NSString).pathExtension.lowercased()) && pixels($0) > 0 }
            .max { (pixels($0), $0) < (pixels($1), $1) }
            .map { own.appendingPathComponent($0) }
    }

    /// What decides whether a cover is sent again: which file it is and when Apple Books wrote it.
    static func fingerprint(_ file: URL) -> String {
        let at = (try? file.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
        return "\(file.lastPathComponent)|\(Int(at?.timeIntervalSince1970 ?? 0))"
    }

    /// The picture as a JPEG no longer than `longestSide`, or nil for a file ImageIO cannot read.
    static func jpeg(_ file: URL) -> Data? {
        guard let source = CGImageSourceCreateWithURL(file as CFURL, nil),
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                  kCGImageSourceCreateThumbnailFromImageAlways: true,
                  kCGImageSourceCreateThumbnailWithTransform: true,
                  kCGImageSourceThumbnailMaxPixelSize: longestSide,
              ] as CFDictionary) else { return nil }
        let out = NSMutableData()
        guard let target = CGImageDestinationCreateWithData(out, UTType.jpeg.identifier as CFString, 1, nil) else {
            return nil
        }
        CGImageDestinationAddImage(target, image, [kCGImageDestinationLossyCompressionQuality: 0.8] as CFDictionary)
        guard CGImageDestinationFinalize(target), out.length <= maxBytes else { return nil }
        return out as Data
    }

    /// The covers not yet accepted by this memory, up to `maxPerSync`: `(asset, fingerprint, jpeg)`.
    static func unsent(assets: [String], folder: URL, sent: [String: String]) -> [(String, String, Data)] {
        var out: [(String, String, Data)] = []
        for asset in assets where out.count < maxPerSync {
            guard let file = bestFile(asset: asset, in: folder) else { continue }
            let stamp = fingerprint(file)
            if sent[asset] == stamp { continue }
            if let data = jpeg(file) { out.append((asset, stamp, data)) }
        }
        return out
    }
}

struct AppleBooksCoverPost: Encodable, Sendable {
    struct Cover: Encodable, Sendable { let assetId: String; let coverB64: String }
    let covers: [Cover]
}

struct AppleBooksCoverReply: Decodable, Sendable { let stored: Int }

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
    /// Re-check of #600: highlights past a book's cap that were not kept, per book (asset id → count); absent from a
    /// server before the cap was said.
    let trimmedBooks: [String: Int]?
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
        guard let library = try AppleBooksPaths.library(in: documents) else { throw AppleBooksReadError.notInstalled }
        let scratch = FileManager.default.temporaryDirectory
            .appendingPathComponent("cicada-apple-books-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: scratch) }
        func copy(_ url: URL) throws -> URL {
            let target = scratch.appendingPathComponent(url.lastPathComponent)
            do {
                try FileManager.default.copyItem(at: url, to: target)
            } catch {
                throw BrowserFileError.classify(error, file: .appleBooksLibrary, path: url.path)
            }
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

    /// The person chooses what enters memory: a book memory has already accepted is kept current (`update`); one it has
    /// never seen waits for the person (`fresh`) unless they declined it (`skipped`); a hidden book that is new is
    /// neither posted nor asked about.
    static func partition(_ books: [AppleBooksBookRecord], sent: [String: String], skipped: Set<String>)
        -> (update: [AppleBooksBookRecord], fresh: [AppleBooksBookRecord]) {
        var update: [AppleBooksBookRecord] = [], fresh: [AppleBooksBookRecord] = []
        for book in books {
            if let stamp = sent[book.assetId] {
                if stamp != fingerprint(book) { update.append(book) }
            } else if !book.isHidden && !skipped.contains(book.assetId) {
                fresh.append(book)
            }
        }
        return (update, fresh)
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
    func postAppleBooksCovers(_ post: AppleBooksCoverPost) async throws -> AppleBooksCoverReply
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
        /// New books found, none posted yet: the person picks which go into memory.
        case choosing(books: Int)
        /// `notKept`: highlights past their book's cap, said on the row (never silent).
        case synced(at: Date, books: Int, highlights: Int, notKept: Int)
        case failed(String)
    }

    nonisolated static let channel = "apple-books"
    nonisolated static let enabledKey = "cicada.appleBooks.enabled"
    nonisolated static let sentKey = "cicada.appleBooks.sent"
    /// Per memory: the books over their cap and how many highlights each left out, so a book not sent again (unchanged)
    /// still counts.
    nonisolated static let notKeptKey = "cicada.appleBooks.notKept"
    /// Per memory: the covers it accepted (asset id → `AppleBooksCovers.fingerprint`).
    nonisolated static let coversKey = "cicada.appleBooks.covers"
    /// Per memory: the asset ids the person declined, never asked about again.
    nonisolated static let skippedKey = "cicada.appleBooks.skipped"
    static let shared = AppleBooksReader()

    private(set) var status: Status = .off
    private(set) var enabled: Bool
    /// New books waiting for the person's choice (nothing about them has left this Mac).
    private(set) var pending: [AppleBooksBookRecord] = []
    @ObservationIgnored private var lastRead: [AppleBooksBookRecord] = []

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

    /// The last read was refused by macOS: the page offers the Full Disk Access pane beside the sentence.
    private(set) var deniedByMac = false

    var isInstalled: Bool { (try? AppleBooksPaths.library(in: documents)) != nil || FileManager.default.fileExists(
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
        pending = []
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
        deniedByMac = false
        let books: [AppleBooksBookRecord]
        switch read {
        case .success(let all): books = all
        case .failure(let error):
            if case BrowserFileError.notReadable = error {
                deniedByMac = true
                status = .failed(Copy.appleBooksDenied)
            } else {
                status = .failed((error as? LocalizedError)?.errorDescription ?? Copy.appleBooksUnreadable)
            }
            return
        }
        var sent = (defaults.dictionary(forKey: sentKey()) as? [String: String]) ?? [:]
        let skipped = Set(defaults.stringArray(forKey: Self.skippedKey + "." + bank()) ?? [])
        let parts = AppleBooksStore.partition(books, sent: sent, skipped: skipped)
        lastRead = books
        pending = parts.fresh
        let changed = parts.update
        var highlights = 0
        let notKeptKey = Self.notKeptKey + "." + bank()
        var notKept = (defaults.dictionary(forKey: notKeptKey) as? [String: Int]) ?? [:]
        do {
            for start in stride(from: 0, to: changed.count, by: 500) {
                let chunk = Array(changed[start..<min(start + 500, changed.count)])
                let result = try await api.syncAppleBooks(AppleBooksSyncPayload(books: chunk))
                guard gen == generation else { return }
                highlights += result.highlights
                for book in chunk {
                    sent[book.assetId] = AppleBooksStore.fingerprint(book)
                    notKept[book.assetId] = result.trimmedBooks?[book.assetId]
                }
                defaults.set(sent, forKey: sentKey())
                defaults.set(notKept, forKey: notKeptKey)
            }
        } catch {
            guard gen == generation else { return }
            status = .failed(Self.failureMessage(error))
            return
        }
        guard gen == generation else { return }
        finishSync(books: books, sent: sent, highlights: highlights, notKept: notKept, generation: gen)
    }

    /// The person's choice: the picked books are posted, the rest are declined and not asked about again.
    func addChosen(_ ids: Set<String>) async {
        guard enabled, !inFlight else { return }
        inFlight = true
        defer { inFlight = false }
        let gen = generation
        let chosen = pending.filter { ids.contains($0.assetId) }
        let declined = pending.map(\.assetId).filter { !ids.contains($0) }
        var sent = (defaults.dictionary(forKey: sentKey()) as? [String: String]) ?? [:]
        let notKeptKey = Self.notKeptKey + "." + bank()
        var notKept = (defaults.dictionary(forKey: notKeptKey) as? [String: Int]) ?? [:]
        var highlights = 0
        do {
            for start in stride(from: 0, to: chosen.count, by: 500) {
                let chunk = Array(chosen[start..<min(start + 500, chosen.count)])
                let result = try await api.syncAppleBooks(AppleBooksSyncPayload(books: chunk))
                guard gen == generation else { return }
                highlights += result.highlights
                for book in chunk {
                    sent[book.assetId] = AppleBooksStore.fingerprint(book)
                    notKept[book.assetId] = result.trimmedBooks?[book.assetId]
                }
                defaults.set(sent, forKey: sentKey())
                defaults.set(notKept, forKey: notKeptKey)
                pending.removeAll { book in chunk.contains { $0.assetId == book.assetId } }
            }
        } catch {
            guard gen == generation else { return }
            status = .failed(Self.failureMessage(error))
            return
        }
        let key = Self.skippedKey + "." + bank()
        defaults.set(Array(Set(defaults.stringArray(forKey: key) ?? []).union(declined)), forKey: key)
        pending = []
        finishSync(books: lastRead, sent: sent, highlights: highlights, notKept: notKept, generation: gen)
    }

    private func finishSync(books: [AppleBooksBookRecord], sent: [String: String], highlights: Int,
                            notKept: [String: Int], generation gen: Int) {
        if !pending.isEmpty { status = .choosing(books: pending.count) }
        let books = books.filter { sent[$0.assetId] != nil }
        let total = books.reduce(0) { $0 + $1.annotations.filter { !($0.selectedText ?? "").isEmpty }.count }
        if pending.isEmpty {
            status = .synced(at: now(), books: books.filter { !$0.isHidden }.count, highlights: max(total, highlights),
                             notKept: notKept.values.reduce(0, +))
        }
        Task { await sendCovers(assets: AppleBooksCovers.assets(of: books), generation: gen) }
    }

    /// Ruling 61: the covers Apple Books keeps, after the books themselves. Best-effort and said nowhere: a book with no
    /// cover here draws nothing, and the next sync goes on from what was accepted.
    private func sendCovers(assets: [String], generation gen: Int) async {
        let key = Self.coversKey + "." + bank()
        var sent = (defaults.dictionary(forKey: key) as? [String: String]) ?? [:]
        let already = sent
        let folder = AppleBooksCovers.folder(documents: documents)
        let unsent = await Task.detached(priority: .utility) {
            AppleBooksCovers.unsent(assets: assets, folder: folder, sent: already)
        }.value
        for start in stride(from: 0, to: unsent.count, by: AppleBooksCovers.perPost) {
            let chunk = Array(unsent[start..<min(start + AppleBooksCovers.perPost, unsent.count)])
            let post = AppleBooksCoverPost(covers: chunk.map { .init(assetId: $0.0, coverB64: $0.2.base64EncodedString()) })
            guard (try? await api.postAppleBooksCovers(post)) != nil, gen == generation else { return }
            for item in chunk { sent[item.0] = item.1 }
            defaults.set(sent, forKey: key)
        }
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
