import SQLite3
import XCTest
@testable import CicadaApp

/// G134 / R-N1 / R-LS21 — a synthetic `flow.sqlite` with every forbidden column
/// present and full of canaries. Nothing forbidden, deleted, demo or unfinished
/// may appear in what the reader would post.
final class WisprFlowReaderTests: XCTestCase {
    private var root: URL!

    private static let schema = """
    CREATE TABLE Meetings (id TEXT, title TEXT, createdAt TEXT, modifiedAt TEXT, endedAt TEXT, isDeleted INTEGER,
      finalized INTEGER, isTourDemo INTEGER, transcriptDeletedAt TEXT, participantNames TEXT, speakerMap TEXT,
      notes TEXT, summary TEXT, audio BLOB, screenshot BLOB, url TEXT);
    INSERT INTO Meetings VALUES ('m-1','alpha-project sync','2026-09-01T10:00:00Z','2026-09-01T11:00:00Z',NULL,0,1,0,
      NULL,'["bob-example"]','{"1":"bob-example"}','notes','summary','CANARY-audio','CANARY-screenshot','CANARY-url');
    INSERT INTO Meetings VALUES ('m-2','deleted','2026-09-02T10:00:00Z','2026-09-02T11:00:00Z',NULL,1,1,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
    INSERT INTO Meetings VALUES ('m-3','demo','2026-09-03T10:00:00Z','2026-09-03T11:00:00Z',NULL,0,1,1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
    INSERT INTO Meetings VALUES ('m-4','draft','2026-09-04T10:00:00Z','2026-09-04T11:00:00Z',NULL,0,0,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
    CREATE TABLE Notes (id TEXT, title TEXT, content TEXT, createdAt INTEGER, modifiedAt INTEGER, isDeleted INTEGER, axText TEXT);
    INSERT INTO Notes VALUES ('n-1','Idea','Try a folder source.',1756717200000,1756717300000,0,'CANARY-axText');
    CREATE TABLE Todos (meetingId TEXT, title TEXT, status TEXT, isDeleted INTEGER);
    INSERT INTO Todos VALUES ('m-1','Send the deck','open',0);
    INSERT INTO Todos VALUES ('m-9','Another meeting','open',0);
    INSERT INTO Todos VALUES ('m-1','CANARY-deleted-todo','open',1);
    CREATE TABLE History (timestamp TEXT, formattedText TEXT, editedText TEXT, app TEXT, numWords INTEGER, asrText TEXT,
      audio BLOB, screenshot BLOB, builtInAudio BLOB, axText TEXT, axHTML TEXT, textboxContents TEXT, pastedText TEXT, url TEXT);
    INSERT INTO History VALUES ('2026-09-01T09:00:00Z','Hello there','Hello there.','com.apple.mail',2,'CANARY-asrText',
      'CANARY-audio','CANARY-screenshot','CANARY-builtInAudio','CANARY-axText','CANARY-axHTML','CANARY-textbox',
      'CANARY-pasted','CANARY-url');
    """

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("WisprFlowReaderTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root.appendingPathComponent("meetings/m-1"), withIntermediateDirectories: true)
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(root.appendingPathComponent("flow.sqlite").path, &db), SQLITE_OK)
        defer { sqlite3_close(db) }
        XCTAssertEqual(sqlite3_exec(db, Self.schema, nil, nil, nil), SQLITE_OK)
        let ndjson = """
        {"id":"u1","timestamp":"2026-09-01T10:01:00Z","text":"I will send the deck","speaker":{"id":1,"source":"system","name":null},"audioOffset":"CANARY-nd"}
        {"id":"u2","timestamp":"2026-09-01T10:02:00Z","text":"Thanks","speaker":{"id":2,"source":"mic","name":"Ada Example"}}
        """
        try ndjson.write(to: root.appendingPathComponent("meetings/m-1/refined.ndjson"), atomically: true, encoding: .utf8)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: root) }

    private func object(_ pass: WisprFlowPass) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: pass.json) as? [String: Any])
    }

    func testTheWhitelistsNeverNameAForbiddenColumn() {
        let allowed = Set(WisprFlowColumns.meetings + WisprFlowColumns.notes + WisprFlowColumns.todos + WisprFlowColumns.history)
        XCTAssertTrue(allowed.isDisjoint(with: WisprFlowColumns.forbidden))
    }

    func testAFirstPassProjectsOnlyFinishedMeetingsNotesAndTheirTodos() throws {
        let pass = try WisprFlowReader(root: root).read(since: WisprFlowCursor(), includeDictation: false)
        let text = String(decoding: pass.json, as: UTF8.self)
        XCTAssertFalse(text.contains("CANARY"), "a forbidden column or ndjson key crossed")
        let body = try object(pass)
        let meetings = try XCTUnwrap(body["meetings"] as? [[String: Any]])
        XCTAssertEqual(meetings.compactMap { ($0["row"] as? [String: Any])?["id"] as? String }, ["m-1"])
        let utterances = try XCTUnwrap(meetings[0]["utterances"] as? [[String: Any]])
        XCTAssertEqual(utterances.count, 2)
        XCTAssertEqual(Set(utterances[1].keys), ["timestamp", "text", "speaker"])
        XCTAssertEqual((body["todos"] as? [[String: Any]])?.compactMap { $0["title"] as? String }, ["Send the deck"])
        XCTAssertEqual((body["notes"] as? [[String: Any]])?.count, 1)
        XCTAssertNil(body["history"], "dictation is opt-in (R-LS23)")
        XCTAssertEqual(pass.cursor.meetings, .text("2026-09-01T11:00:00Z"))
        XCTAssertEqual(pass.cursor.notes, .int(1_756_717_300_000))
        XCTAssertFalse(pass.hasMore)
    }

    func testDictationOnlyWhenAskedAndOnlyItsFiveColumns() throws {
        let pass = try WisprFlowReader(root: root).read(since: WisprFlowCursor(), includeDictation: true)
        let history = try XCTUnwrap(try object(pass)["history"] as? [[String: Any]])
        XCTAssertEqual(Set(history[0].keys), Set(WisprFlowColumns.history))
        XCTAssertFalse(String(decoding: pass.json, as: UTF8.self).contains("CANARY"))
    }

    func testALaterPassReadsPastTheCursorAndReportsDeletions() throws {
        let reader = WisprFlowReader(root: root)
        let first = try reader.read(since: WisprFlowCursor(), includeDictation: false)
        let second = try reader.read(since: first.cursor, includeDictation: false)
        let body = try object(second)
        XCTAssertEqual((body["meetings"] as? [[String: Any]])?.count, 0)
        XCTAssertEqual(body["deletedMeetingIds"] as? [String], ["m-2"])
        XCTAssertFalse(second.isEmpty)
        // Review r1: the cursor moved past the deletion, so it is posted once.
        XCTAssertEqual(second.cursor.meetings, .text("2026-09-02T11:00:00Z"))
        XCTAssertTrue(try reader.read(since: second.cursor, includeDictation: false).isEmpty)
    }

    /// Review r1: rows sharing one `modifiedAt` across a batch boundary (a bulk
    /// import) are all read — the cursor is `(modifiedAt, id)`, not `modifiedAt`.
    func testRowsSharingATimestampAcrossABatchAreAllRead() throws {
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(root.appendingPathComponent("flow.sqlite").path, &db), SQLITE_OK)
        for i in 1...5 {
            XCTAssertEqual(sqlite3_exec(db, "INSERT INTO Notes VALUES ('bulk-\(i)','Imported','text',1,1756717400000,0,NULL)",
                                        nil, nil, nil), SQLITE_OK)
        }
        sqlite3_close(db)
        var reader = WisprFlowReader(root: root)
        reader.batchLimit = 2
        var cursor = WisprFlowCursor()
        var seen: [String] = []
        for _ in 0..<10 {
            let pass = try reader.read(since: cursor, includeDictation: false)
            seen += (try object(pass)["notes"] as? [[String: Any]] ?? []).compactMap { $0["id"] as? String }
            cursor = pass.cursor
            if !pass.hasMore { break }
        }
        XCTAssertEqual(seen, ["n-1", "bulk-1", "bulk-2", "bulk-3", "bulk-4", "bulk-5"])
    }

    /// A cursor saved before the `(modifiedAt, id)` halves existed still decodes.
    func testAnOlderCursorStillDecodes() throws {
        let old = Data(#"{"meetings":{"text":{"_0":"2026-09-01T11:00:00Z"}}}"#.utf8)
        let cursor = try JSONDecoder().decode(WisprFlowCursor.self, from: old)
        XCTAssertEqual(cursor.meetings, .text("2026-09-01T11:00:00Z"))
        XCTAssertNil(cursor.meetingsId)
    }

    func testAMissingStoreSaysSoWithTheWisprFlowFile() {
        let reader = WisprFlowReader(root: root.appendingPathComponent("nope"))
        XCTAssertThrowsError(try reader.read(since: WisprFlowCursor(), includeDictation: false)) { error in
            guard case BrowserFileError.missing(let file, _) = error else { return XCTFail("\(error)") }
            XCTAssertEqual(file, .wisprFlowDatabase)
        }
    }
}
