import CryptoKit
import Foundation
import Observation
import SQLite3

/// G43 — the columns the app may read from Voice Memos' `CloudRecordings.db`, named once. Each is taken only if the table
/// has it (`SQLiteReadOnly.columns`): the schema below is Core Data's usual naming and was NOT checked against a live
/// store (the owner's recordings are never read in development), so anything missing reads as "no recording".
enum VoiceMemosColumns {
    static let recordings = ["ZUNIQUEID", "ZPATH", "ZCUSTOMLABEL", "ZDATE", "ZDURATION", "ZTRASHEDDATE"]
    static let table = "ZCLOUDRECORDING"
}

/// Where Voice Memos keeps its recordings and the database naming them.
enum VoiceMemosPaths {
    static let databaseName = "CloudRecordings.db"

    /// `NSHomeDirectory()` honours `CFFIXED_USER_HOME`, so a scratch home never reaches the real container.
    static func recordings(home: URL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)) -> URL {
        home.appendingPathComponent("Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings",
                                    isDirectory: true)
    }

    /// An absent folder is nil (nothing recorded yet); one macOS refuses to list throws, so a denial is never read as
    /// "no recordings" (the capture rail: an unreadable file shows the exact fix).
    static func database(in folder: URL) throws -> URL? {
        do {
            _ = try FileManager.default.contentsOfDirectory(atPath: folder.path)
        } catch {
            let refusal = BrowserFileError.classify(error, file: .voiceMemosStore, path: folder.path)
            if case .missing = refusal { return nil }
            throw refusal
        }
        let db = folder.appendingPathComponent(databaseName)
        return FileManager.default.fileExists(atPath: db.path) ? db : nil
    }

    /// The audio file a row names: only its last path component, only inside `folder`, only an audio type that is
    /// there. An absolute or `..` path in a row never leaves the folder; an evicted (iCloud-only) recording is not there.
    static func audio(named path: String, in folder: URL) -> URL? {
        let name = (path as NSString).lastPathComponent
        guard !name.isEmpty, !name.hasPrefix("."), name == (name as NSString).lastPathComponent else { return nil }
        let url = folder.appendingPathComponent(name)
        guard MediaKind.of(url) == .audio, FileManager.default.fileExists(atPath: url.path) else { return nil }
        return url
    }

    /// `media_files.source_file_id("voice_memos", key)`: the item's id on the backend, so a hit finds its file here.
    static func fileId(key: String) -> String {
        SHA256.hash(data: Data("voice_memos:\(key)".utf8)).map { String(format: "%02x", $0) }.joined().prefix(16).description
    }

    static func keyIsValid(_ key: String) -> Bool {
        !key.isEmpty && key.count <= 128 && key.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || "._-".contains($0)) }
    }
}

struct VoiceMemoRecord: Equatable, Sendable {
    let key: String
    let title: String
    /// The recording's own date (ruling 39).
    let recordedAt: Date
    let duration: Double?  // motion-lint:ok — a recording's length
    let file: URL
}

/// The read itself, pure and off the main actor: copy the database with its `-wal` and `-shm` into a temporary folder
/// (Voice Memos keeps writing; the Chrome-history rule), open the copy read-only, read the whitelisted columns, delete
/// the copy. Core Data dates are seconds since 2001-01-01.
enum VoiceMemosStore {
    static func snapshot(folder: URL) throws -> [VoiceMemoRecord] { try snapshotAll(folder: folder).records }

    /// What can be read now, and every recording the store lists, whether or not its audio is on this Mac. An iCloud-only
    /// memo has no file here and still exists, so only `listed` says what has left (review of #644).
    static func snapshotAll(folder: URL) throws -> (records: [VoiceMemoRecord], listed: [String]) {
        guard let database = try VoiceMemosPaths.database(in: folder) else { throw VoiceMemosReadError.notInstalled }
        let scratch = FileManager.default.temporaryDirectory
            .appendingPathComponent("cicada-voice-memos-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: scratch) }
        let target = scratch.appendingPathComponent(database.lastPathComponent)
        do {
            try FileManager.default.copyItem(at: database, to: target)
        } catch {
            throw BrowserFileError.classify(error, file: .voiceMemosStore, path: database.path)
        }
        for suffix in ["-wal", "-shm"] {
            let side = URL(fileURLWithPath: database.path + suffix)
            if FileManager.default.fileExists(atPath: side.path) {
                try? FileManager.default.copyItem(at: side, to: URL(fileURLWithPath: target.path + suffix))
            }
        }
        AppleBooksStore.settle(target)
        return try read(database: target, folder: folder)
    }

    static func read(database: URL, folder: URL) throws -> (records: [VoiceMemoRecord], listed: [String]) {
        let db = try SQLiteReadOnly(url: database)
        defer { db.close() }
        let cols = db.columns(of: VoiceMemosColumns.table, whitelist: VoiceMemosColumns.recordings)
        guard cols.contains("ZUNIQUEID"), cols.contains("ZPATH") else { throw VoiceMemosReadError.unreadable }
        let rows = try db.query("SELECT \(cols.joined(separator: ", ")) FROM \(VoiceMemosColumns.table)", binds: [])
        let listed = rows.compactMap { row -> String? in
            guard let key = row["ZUNIQUEID"] as? String, VoiceMemosPaths.keyIsValid(key),
                  (row["ZTRASHEDDATE"] as? NSNumber) == nil else { return nil }
            return key
        }
        let records: [VoiceMemoRecord] = rows.compactMap { row in
            guard let key = row["ZUNIQUEID"] as? String, VoiceMemosPaths.keyIsValid(key),
                  (row["ZTRASHEDDATE"] as? NSNumber) == nil,
                  let path = row["ZPATH"] as? String, let file = VoiceMemosPaths.audio(named: path, in: folder)
            else { return nil }
            let label = (row["ZCUSTOMLABEL"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let seconds = (row["ZDATE"] as? NSNumber)?.doubleValue ?? 0
            let modified = (try? file.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
            // A row with no date is dated by its file, never by "now".
            guard let when = seconds > 0 ? Date(timeIntervalSinceReferenceDate: seconds) : modified else { return nil }
            return VoiceMemoRecord(key: key, title: label.isEmpty ? file.deletingPathExtension().lastPathComponent : label,
                                   recordedAt: when, duration: (row["ZDURATION"] as? NSNumber)?.doubleValue, file: file)  // motion-lint:ok — a recording's length
        }.sorted { ($0.recordedAt, $0.key) < ($1.recordedAt, $1.key) }
        return (records, listed)
    }

    /// What decides whether a recording is read again: its file's size and write time (an edit changes both). The
    /// backend still compares the bytes' sha256, so a touched but identical file is `unchanged` there.
    static func fingerprint(_ record: VoiceMemoRecord) -> String {
        let values = try? record.file.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
        return "\(values?.fileSize ?? 0)|\(Int(values?.contentModificationDate?.timeIntervalSince1970 ?? 0))"
    }

    static func iso(_ date: Date) -> String { ISO8601DateFormatter().string(from: date) }
}

enum VoiceMemosReadError: Error, LocalizedError, Equatable {
    case notInstalled, unreadable
    var errorDescription: String? {
        switch self {
        case .notInstalled: Copy.voiceMemosMissing
        case .unreadable: Copy.voiceMemosUnreadable
        }
    }
}

protocol VoiceMemosAPI: Sendable {
    /// `POST /files/voice-memos`: ≤ 20 memos (the app sends one), then optionally the complete list of ids.
    func postVoiceMemos(_ body: [String: Any]) async throws
}

extension APIClient: VoiceMemosAPI {
    func postVoiceMemos(_ body: [String: Any]) async throws {
        let _: [String: Int] = try await postVideo("/files/voice-memos", body: body)
    }
}

/// G43 — Voice Memos, read by the APP after the person turns it on: the words of each recording are made on this Mac
/// (`MediaFileIndexer`'s recogniser) and posted as derivatives to `media_files`, outside every bank. The audio never
/// leaves the Mac and the words are the recording's, never the person's own (never read by Sleep). One item per
/// recording, keyed by its id; an edit re-stages it, a recording Voice Memos no longer lists is tombstoned. Speech
/// Recognition is asked for only inside the person's own Connect. On launch, every few hours, after a bank switch, and
/// on Refresh. Turn off stops all of it and deletes nothing.
@MainActor
@Observable
final class VoiceMemosReader {
    enum Status: Equatable {
        case off
        case syncing
        /// `withoutWords`: recordings kept out of search for want of words (no speech model, or nothing said).
        case synced(at: Date, memos: Int, withoutWords: Int)
        case failed(String)
    }

    nonisolated static let channel = "voice-memos"
    nonisolated static let enabledKey = "cicada.voiceMemos.enabled"
    nonisolated static let sentKey = "cicada.voiceMemos.sent"
    /// The title each recording had when it was last posted (ROR-122): a rename in Voice Memos moves no byte, so the
    /// fingerprint cannot see it.
    nonisolated static let namesKey = "cicada.voiceMemos.names"
    static let shared = VoiceMemosReader()

    private(set) var status: Status = .off
    private(set) var enabled: Bool
    /// The last read was refused by macOS: the page offers the Full Disk Access pane beside the sentence.
    private(set) var deniedByMac = false

    @ObservationIgnored private let api: VoiceMemosAPI
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let folder: URL
    @ObservationIgnored private let speech: any SpeechAuthorizing
    @ObservationIgnored private let transcriber: any Transcribing
    @ObservationIgnored private let places: MediaFilePlaces
    @ObservationIgnored private let locale: Locale
    @ObservationIgnored private let bank: () -> String
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let period: Duration
    @ObservationIgnored private var periodic: Task<Void, Never>?
    @ObservationIgnored private var inFlight = false
    @ObservationIgnored private var generation = 0

    init(api: VoiceMemosAPI = APIClient.shared, defaults: UserDefaults = .standard,
         folder: URL = VoiceMemosPaths.recordings(), speech: any SpeechAuthorizing = SystemSpeechAuthorizer(),
         transcriber: any Transcribing = SystemTranscriber(), places: MediaFilePlaces = MediaFilePlaces(),
         locale: Locale = .current, bank: @escaping () -> String = { BankScope.value(method: "POST") ?? "default" },
         now: @escaping () -> Date = Date.init, period: Duration = .seconds(3 * 60 * 60)) {
        self.api = api; self.defaults = defaults; self.folder = folder; self.speech = speech
        self.transcriber = transcriber; self.places = places; self.locale = locale; self.bank = bank; self.now = now
        self.period = period
        enabled = defaults.bool(forKey: Self.enabledKey)
    }

    var isInstalled: Bool { FileManager.default.fileExists(atPath: folder.path) }

    func start() {
        guard enabled else { status = .off; return }
        arm()
        Task { await sync() }
    }

    /// The person's Connect: the one place Speech Recognition may be asked for.
    func turnOn() async {
        if speech.status() == .notDetermined { _ = await speech.request() }
        generation += 1
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
    }

    func syncNow() async { guard enabled else { return }; await sync() }

    /// A bank switch: the new memory has not seen these recordings.
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
    private func namesKey() -> String { Self.namesKey + "." + bank() }

    /// A recording already posted whose title changed since: the name alone goes (`nameOnly`, so the backend takes the
    /// name and never touches the words). `names` holds a title only for a recording that was actually posted, so one
    /// listened to and found silent, or never posted, is never renamed on the backend.
    nonisolated static func renamed(_ records: [VoiceMemoRecord], sent: [String: String], names: [String: String])
        -> [VoiceMemoRecord] {
        records.filter { record in
            guard sent[record.key] == VoiceMemosStore.fingerprint(record), let was = names[record.key] else { return false }
            return was != record.title
        }
    }

    private func sync() async {
        guard !inFlight, enabled else { return }
        inFlight = true
        defer { inFlight = false }
        let gen = generation
        status = .syncing
        let folder = self.folder
        let read = await Task.detached(priority: .utility) { () -> Result<(records: [VoiceMemoRecord], listed: [String]), Error> in
            Result { try VoiceMemosStore.snapshotAll(folder: folder) }
        }.value
        guard gen == generation, enabled else { return }
        deniedByMac = false
        let records: [VoiceMemoRecord]
        let listed: [String]
        switch read {
        case .success(let all): (records, listed) = all
        case .failure(let error):
            if case BrowserFileError.notReadable = error {
                deniedByMac = true
                status = .failed(Copy.appleBooksDenied)
            } else {
                status = .failed((error as? LocalizedError)?.errorDescription ?? Copy.voiceMemosUnreadable)
            }
            return
        }
        guard speech.status() == .authorized else {
            status = .failed(Copy.mediaSpeechDenied)
            return
        }
        for record in records { places.remember(VoiceMemosPaths.fileId(key: record.key), record.file) }
        var sent = (defaults.dictionary(forKey: sentKey()) as? [String: String]) ?? [:]
        var names = (defaults.dictionary(forKey: namesKey()) as? [String: String]) ?? [:]
        var withoutWords = 0
        do {
            for record in records where sent[record.key] != VoiceMemosStore.fingerprint(record) {
                guard gen == generation, enabled else { return }
                let stamp = VoiceMemosStore.fingerprint(record)
                let outcome = await transcriber.transcribe(record.file, locale: locale)
                guard case .words(let segments) = outcome, !segments.isEmpty else {
                    withoutWords += 1
                    // Listened to and nothing said: not again until it changes. A missing speech model retries.
                    if case .words = outcome {
                        sent[record.key] = stamp
                        defaults.set(sent, forKey: sentKey())
                    }
                    continue
                }
                var body: [String: Any] = [
                    "key": record.key, "name": record.title, "recordedAt": VoiceMemosStore.iso(record.recordedAt),
                    "language": locale.identifier(.bcp47), "transcribedBy": MediaFileIndexer.transcriberName,
                    "segments": segments.map { ["start": $0.start, "end": $0.end, "text": $0.text] },
                ]
                if let sha = MediaFileIndexer.sha256(of: record.file) { body["sha256"] = sha }
                if let size = try? record.file.resourceValues(forKeys: [.fileSizeKey]).fileSize { body["size"] = size }
                if let d = record.duration ?? segments.last?.end { body["durationS"] = d }
                try await api.postVoiceMemos(["memos": [body]])
                guard gen == generation else { return }
                sent[record.key] = stamp
                defaults.set(sent, forKey: sentKey())
                names[record.key] = record.title
                defaults.set(names, forKey: namesKey())
            }
            for record in Self.renamed(records, sent: sent, names: names) {
                guard gen == generation, enabled else { return }
                let body: [String: Any] = ["key": record.key, "name": record.title, "nameOnly": true,
                                           "recordedAt": VoiceMemosStore.iso(record.recordedAt), "segments": []]
                try await api.postVoiceMemos(["memos": [body]])
                names[record.key] = record.title
            }
            defaults.set(names, forKey: namesKey())
            // A complete, successful read: what Voice Memos no longer lists leaves search (tombstoned).
            try await api.postVoiceMemos(["memos": [] as [[String: Any]], "present": listed])
        } catch {
            guard gen == generation else { return }
            status = .failed(Self.failureMessage(error))
            return
        }
        sent = sent.filter { key, _ in listed.contains(key) }
        defaults.set(sent, forKey: sentKey())
        defaults.set(names.filter { key, _ in listed.contains(key) }, forKey: namesKey())
        status = .synced(at: now(), memos: records.count - withoutWords, withoutWords: withoutWords)
    }

    static func failureMessage(_ error: Error) -> String {
        if error is URLError { return Copy.calendarBackendDown }
        guard let api = error as? APIError else { return Copy.voiceMemosSyncFailed }
        switch api {
        case .httpError(409, let body): return ProjectWriteFailure.detail(body) ?? Copy.voiceMemosSyncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.voiceMemosNeedsUpdate
        case .serverUnreachable: return Copy.calendarBackendDown
        default: return Copy.voiceMemosSyncFailed
        }
    }

    /// The area's one line: what the reader is doing, what is in, or its failure.
    static func line(_ status: Status, locale: Locale = .autoupdatingCurrent) -> (text: String, isProblem: Bool)? {
        switch status {
        case .off: return nil
        case .syncing: return (Copy.voiceMemosSyncing, false)
        case .failed(let why): return (why, true)
        case .synced(_, let memos, let without):
            let held = Copy.voiceMemosHolds(memos, locale: locale)
            return (without > 0 ? held + " · " + Copy.voiceMemosWithoutWords(without, locale: locale) : held, false)
        }
    }
}
