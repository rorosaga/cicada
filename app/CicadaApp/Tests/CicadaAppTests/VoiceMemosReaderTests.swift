import Foundation
import SQLite3
import XCTest
@testable import CicadaApp

/// G43 — the Voice Memos reader: the database copied and read read-only, only the whitelisted columns, a missing column
/// or file reads as "no recording", one item per recording keyed by its id and dated by its own date, an edit read again,
/// a deletion reported. A synthetic store with Core Data's usual names (NOT checked against a live store) and placeholder
/// ids; the recogniser and the backend are fakes, so no Speech prompt is raised.
final class VoiceMemosReaderTests: XCTestCase {
    private var dir: URL!
    private let keyA = "AAAA1111-2222-3333-4444-555566667777"
    private let keyB = "BBBB1111-2222-3333-4444-555566667777"

    override func setUpWithError() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("vm-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: dir) }

    // MARK: Fixtures

    private func audio(_ name: String, bytes: String = "x") throws {
        try Data(bytes.utf8).write(to: dir.appendingPathComponent(name))
    }

    private func store(columns: String = "ZUNIQUEID TEXT, ZPATH TEXT, ZCUSTOMLABEL TEXT, ZDATE REAL, ZDURATION REAL, ZTRASHEDDATE REAL",
                       rows: [String]) throws {
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(dir.appendingPathComponent(VoiceMemosPaths.databaseName).path, &db), SQLITE_OK)
        defer { sqlite3_close(db) }
        XCTAssertEqual(sqlite3_exec(db, "CREATE TABLE ZCLOUDRECORDING (Z_PK INTEGER PRIMARY KEY, \(columns))", nil, nil, nil),
                       SQLITE_OK)
        for row in rows { XCTAssertEqual(sqlite3_exec(db, "INSERT INTO ZCLOUDRECORDING VALUES (NULL, \(row))", nil, nil, nil), SQLITE_OK, row) }
    }

    // MARK: The store

    func testOnlyARecordingWithAFileAndAnIdAndNotInTheTrashIsRead() throws {
        try audio("one.m4a"); try audio("two.m4a"); try audio("gone.m4a"); try audio("note.txt")
        try store(rows: [
            "'\(keyA)', 'one.m4a', 'First', 700000000, 12.5, NULL",
            "'\(keyB)', '/elsewhere/../two.m4a', '', 700000100, 3, NULL",   // a path names only its last component
            "'CCCC-1', 'gone.m4a', 'Trashed', 700000200, 3, 700000300",
            "'DDDD-1', 'missing.m4a', 'Evicted', 700000200, 3, NULL",
            "'../escape', 'one.m4a', 'Bad id', 700000200, 3, NULL",
            "'EEEE-1', 'note.txt', 'Not audio', 700000200, 3, NULL",
        ])
        let records = try VoiceMemosStore.snapshot(folder: dir)
        XCTAssertEqual(records.map(\.key), [keyA, keyB])
        XCTAssertEqual(records[0].title, "First")
        XCTAssertEqual(records[1].title, "two", "an empty label falls back to the file's name")
        XCTAssertEqual(records[0].recordedAt, Date(timeIntervalSinceReferenceDate: 700000000), "its own date")
        XCTAssertEqual(records[0].duration, 12.5)
    }

    func testAMissingColumnOrDatabaseReadsAsNoRecording() throws {
        XCTAssertThrowsError(try VoiceMemosStore.snapshot(folder: dir)) {
            XCTAssertEqual($0 as? VoiceMemosReadError, .notInstalled)
        }
        try audio("one.m4a")
        try store(columns: "ZUNIQUEID TEXT", rows: ["'\(keyA)'"])
        XCTAssertThrowsError(try VoiceMemosStore.snapshot(folder: dir)) {
            XCTAssertEqual($0 as? VoiceMemosReadError, .unreadable, "no path column: nothing to find a recording by")
        }
    }

    func testARowWithoutADateIsDatedByItsFileNeverByNow() throws {
        try audio("one.m4a")
        try store(columns: "ZUNIQUEID TEXT, ZPATH TEXT", rows: ["'\(keyA)', 'one.m4a'"])
        let record = try XCTUnwrap(VoiceMemosStore.snapshot(folder: dir).first)
        let modified = try XCTUnwrap(dir.appendingPathComponent("one.m4a")
            .resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate)
        XCTAssertEqual(record.recordedAt, modified)
    }

    func testTheItemIdMatchesTheBackendsForTheSameRecording() {
        // `media_files.source_file_id("voice_memos", key)`, pinned in api/tests/test_media_files.py too.
        XCTAssertEqual(VoiceMemosPaths.fileId(key: keyA), "395175071cd9864f")
        XCTAssertTrue(VoiceMemosPaths.keyIsValid(keyA))
        XCTAssertFalse(VoiceMemosPaths.keyIsValid("../x"))
        XCTAssertFalse(VoiceMemosPaths.keyIsValid(""))
    }

    func testTheReadReadsOnlyTheCopyAndLeavesTheOriginalAlone() throws {
        try audio("one.m4a")
        try store(rows: ["'\(keyA)', 'one.m4a', 'First', 700000000, 1, NULL"])
        let path = dir.appendingPathComponent(VoiceMemosPaths.databaseName)
        let before = try Data(contentsOf: path)
        _ = try VoiceMemosStore.snapshot(folder: dir)
        XCTAssertEqual(try Data(contentsOf: path), before)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: dir.path).sorted(),
                       ["CloudRecordings.db", "one.m4a"].sorted())
    }

    // MARK: The reader

    private final class Posts: VoiceMemosAPI, @unchecked Sendable {
        private let lock = NSLock()
        private var bodies: [[String: Any]] = []
        func postVoiceMemos(_ body: [String: Any]) async throws { lock.lock(); bodies.append(body); lock.unlock() }
        var all: [[String: Any]] { lock.lock(); defer { lock.unlock() }; return bodies }
        var memos: [[String: Any]] { all.flatMap { ($0["memos"] as? [[String: Any]]) ?? [] } }
        var lastPresent: [String]? { all.last?["present"] as? [String] }
    }

    private struct Speech: SpeechAuthorizing {
        var access: SpeechAccess
        func status() -> SpeechAccess { access }
        func request() async -> SpeechAccess { access }
    }

    private struct Says: Transcribing {
        var outcome: TranscribeOutcome
        func transcribe(_ url: URL, locale: Locale) async -> TranscribeOutcome { outcome }
    }

    @MainActor
    private func reader(_ api: Posts, speech: SpeechAccess = .authorized,
                        outcome: TranscribeOutcome = .words([TranscriptSegment(start: 0, end: 2, text: "Hello there.")]), transcriber: (any Transcribing)? = nil)
        -> VoiceMemosReader {
        let defaults = UserDefaults(suiteName: "vm-\(UUID().uuidString)")!
        return VoiceMemosReader(api: api, defaults: defaults, folder: dir, speech: Speech(access: speech),
                                transcriber: transcriber ?? Says(outcome: outcome),
                                places: MediaFilePlaces(defaults: defaults), locale: Locale(identifier: "en_US"),
                                bank: { "test" })
    }

    @MainActor
    func testAFirstReadPostsEachRecordingWithItsIdDateAndTranscriberThenTheListOfWhatExists() async throws {
        try audio("one.m4a")
        try store(rows: ["'\(keyA)', 'one.m4a', 'First', 700000000, 5, NULL"])
        let api = Posts()
        let reader = reader(api)
        await reader.turnOn()
        let memo = try XCTUnwrap(api.memos.first)
        XCTAssertEqual(memo["key"] as? String, keyA)
        XCTAssertEqual(memo["recordedAt"] as? String, "2023-03-08T20:26:40Z")
        XCTAssertEqual(memo["transcribedBy"] as? String, MediaFileIndexer.transcriberName)
        XCTAssertEqual((memo["segments"] as? [[String: Any]])?.count, 1)
        XCTAssertNotNil(memo["sha256"])
        XCTAssertEqual(api.lastPresent, [keyA])
        XCTAssertEqual(reader.status, .synced(at: reader.status.at, memos: 1, withoutWords: 0))
        XCTAssertTrue(reader.enabled)
    }

    @MainActor
    func testAnUnchangedRecordingIsNotReadAgainAnEditedOneIsAndADeletedOneLeavesTheList() async throws {
        try audio("one.m4a"); try audio("two.m4a")
        try store(rows: ["'\(keyA)', 'one.m4a', 'First', 700000000, 5, NULL",
                         "'\(keyB)', 'two.m4a', 'Second', 700000100, 5, NULL"])
        let api = Posts()
        let reader = reader(api)
        await reader.turnOn()
        XCTAssertEqual(api.memos.count, 2)
        await reader.syncNow()
        XCTAssertEqual(api.memos.count, 2, "nothing changed: nothing read again")
        try audio("one.m4a", bytes: "a longer recording")
        await reader.syncNow()
        XCTAssertEqual(api.memos.count, 3)
        XCTAssertEqual(api.memos.last?["key"] as? String, keyA)
        // Only in iCloud now: its file is gone from this Mac and the store still lists it, so its words stay.
        try FileManager.default.removeItem(at: dir.appendingPathComponent("two.m4a"))
        await reader.syncNow()
        XCTAssertEqual(Set(api.lastPresent ?? []), [keyA, keyB], "a memo not downloaded has not left")
        try FileManager.default.removeItem(at: dir.appendingPathComponent("CloudRecordings.db"))
        try store(rows: ["'\(keyA)', 'one.m4a', 'First', 700000000, 5, NULL"])
        await reader.syncNow()
        XCTAssertEqual(api.lastPresent, [keyA], "the one the store no longer lists leaves")
    }

    @MainActor
    func testWithoutSpeechAccessNothingIsPostedAndTheReasonIsSaid() async throws {
        try audio("one.m4a")
        try store(rows: ["'\(keyA)', 'one.m4a', 'First', 700000000, 5, NULL"])
        let api = Posts()
        let reader = reader(api, speech: .denied)
        await reader.turnOn()
        XCTAssertEqual(reader.status, .failed(Copy.mediaSpeechDenied))
        XCTAssertTrue(api.all.isEmpty)
    }

    @MainActor
    func testARecordingWithNoWordsIsCountedAndNotPosted() async throws {
        try audio("one.m4a")
        try store(rows: ["'\(keyA)', 'one.m4a', 'First', 700000000, 5, NULL"])
        let api = Posts()
        let reader = reader(api, outcome: .noSpeechModel)
        await reader.turnOn()
        XCTAssertTrue(api.memos.isEmpty)
        XCTAssertEqual(reader.status, .synced(at: reader.status.at, memos: 0, withoutWords: 1))
    }

    private final class Counts: Transcribing, @unchecked Sendable {
        var calls = 0
        var outcome: TranscribeOutcome
        init(_ outcome: TranscribeOutcome) { self.outcome = outcome }
        func transcribe(_ url: URL, locale: Locale) async -> TranscribeOutcome { calls += 1; return outcome }
    }

    @MainActor
    func testASilentMemoIsListenedToOnceAndAMissingModelRetries() async throws {
        try audio("one.m4a")
        try store(rows: ["'\(keyA)', 'one.m4a', 'First', 700000000, 5, NULL"])
        let silent = Counts(.words([]))
        let first = reader(Posts(), transcriber: silent)
        await first.turnOn()
        await first.syncNow()
        XCTAssertEqual(silent.calls, 1, "nothing said: not listened to again until it changes")

        let noModel = Counts(.noSpeechModel)
        let again = reader(Posts(), transcriber: noModel)
        await again.turnOn()
        await again.syncNow()
        XCTAssertEqual(noModel.calls, 2, "no model yet: it retries")
    }

    @MainActor
    func testAMissingFolderIsNeverReadAsADenial() async {
        let api = Posts()
        let reader = reader(api)
        try? FileManager.default.removeItem(at: dir)
        await reader.turnOn()
        XCTAssertEqual(reader.status, .failed(Copy.voiceMemosMissing))
        XCTAssertFalse(reader.deniedByMac)
    }

    func testTheTileDrawsApplesInstalledIconAndIsOffByDefault() {
        XCTAssertEqual(OriginIconography.appBundleId(for: VoiceMemosReader.channel), "com.apple.VoiceMemos")
        XCTAssertFalse(UserDefaults(suiteName: "vm-\(UUID().uuidString)")!.bool(forKey: VoiceMemosReader.enabledKey))
        XCTAssertTrue(OriginIconography.allKnownOrigins.contains(VoiceMemosReader.channel))
    }
}

/// ROR-122: a rename in Voice Memos moves no byte; the reader posts the name alone, and only for a recording it
/// actually posted (a silent one, or one never posted, is never renamed on the backend).
final class VoiceMemosRenameTests: XCTestCase {
    private func record(_ key: String, _ title: String, in dir: URL) throws -> VoiceMemoRecord {
        let file = dir.appendingPathComponent("\(key).m4a")
        try Data("x".utf8).write(to: file)
        return VoiceMemoRecord(key: key, title: title, recordedAt: Date(timeIntervalSince1970: 0), duration: nil, file: file)
    }

    func testOnlyAChangedTitleOfAPostedRecordingIsPosted() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("vmr-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let a = try record("key-a", "New title", in: dir), b = try record("key-b", "Same", in: dir)
        let silent = try record("key-c", "Renamed but silent", in: dir), d = try record("key-d", "Not posted", in: dir)
        // key-c was listened to (sent) and found silent: it has no posted title.
        let sent = ["key-a": VoiceMemosStore.fingerprint(a), "key-b": VoiceMemosStore.fingerprint(b),
                    "key-c": VoiceMemosStore.fingerprint(silent)]
        let out = VoiceMemosReader.renamed([a, b, silent, d], sent: sent, names: ["key-a": "Old title", "key-b": "Same"])
        XCTAssertEqual(out.map(\.key), ["key-a"])
    }
}

private extension VoiceMemosReader.Status {
    /// The time of a `.synced` status (tests compare the rest).
    var at: Date { if case .synced(let at, _, _) = self { return at }; return .distantPast }
}
