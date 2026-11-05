import SQLite3
import XCTest
@testable import CicadaApp

/// ROR-15: a note's pin is read from a copy of Notes' own store, one query for `Z_PK` alone, only with Full Disk
/// Access the app already holds. Every store here is a synthetic SQLite file with the real column names and invented
/// rows; nothing opens the person's Notes.
final class AppleNotesPinsTests: XCTestCase {
    private func fixture(_ rows: [(pk: Int, pinned: Int?, locked: Int?)], extra: String = "") throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("pins-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: dir) }
        let url = dir.appendingPathComponent("NoteStore.sqlite")
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(url.path, &db), SQLITE_OK)
        defer { sqlite3_close(db) }
        var sql = "CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER PRIMARY KEY, ZISPINNED INTEGER, "
            + "ZISPASSWORDPROTECTED INTEGER\(extra));"
        for r in rows {
            let pinned = r.pinned.map(String.init) ?? "NULL", locked = r.locked.map(String.init) ?? "NULL"
            sql += "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, ZISPINNED, ZISPASSWORDPROTECTED) VALUES (\(r.pk), \(pinned), \(locked));"
        }
        XCTAssertEqual(sqlite3_exec(db, sql, nil, nil, nil), SQLITE_OK)
        return url
    }

    private func id(_ pk: Int, entity: String = "ICNote", mark: String = "p") -> String {
        "x-coredata://00000000-0000-0000-0000-000000000000/\(entity)/\(mark)\(pk)"
    }

    func testANotesIdMapsToItsRowKeyAndNothingElseDoes() {
        XCTAssertEqual(AppleNotesPins.rowKey(id(12)), 12)
        XCTAssertNil(AppleNotesPins.rowKey(id(12, entity: "ICFolder")))
        XCTAssertNil(AppleNotesPins.rowKey(id(12, mark: "t")))
        XCTAssertNil(AppleNotesPins.rowKey("x-coredata://u/ICNote/p"))
        XCTAssertNil(AppleNotesPins.rowKey("x-coredata://u/ICNote/p1a"))
        XCTAssertNil(AppleNotesPins.rowKey("x-coredata://u/ICNote/p-3"))
        XCTAssertNil(AppleNotesPins.rowKey("note-a"))
        XCTAssertNil(AppleNotesPins.rowKey(""))
    }

    func testTheQueryReadsKeysOfPinnedUnlockedNotesOnly() throws {
        let store = try fixture([(1, 1, 0), (2, 0, 0), (3, 1, 1), (4, nil, nil), (5, 1, nil), (6, 1, 0)])
        XCTAssertEqual(AppleNotesPins.keys(in: store), [1, 6])
        XCTAssertEqual(AppleNotesPins.query, "SELECT Z_PK FROM ZICCLOUDSYNCINGOBJECT WHERE ZISPINNED = 1 AND ZISPASSWORDPROTECTED = 0")
    }

    func testAStoreWithoutTheColumnsOrTheTableIsNilNeverEmpty() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("pins-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: dir) }
        let url = dir.appendingPathComponent("NoteStore.sqlite")
        var db: OpaquePointer?
        sqlite3_open(url.path, &db)
        sqlite3_exec(db, "CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER PRIMARY KEY, ZISPINNED INTEGER);", nil, nil, nil)
        sqlite3_close(db)
        XCTAssertNil(AppleNotesPins.keys(in: url))
        XCTAssertNil(AppleNotesPins.keys(in: dir.appendingPathComponent("missing.sqlite")))
    }

    func testOnlyIdsAlreadyInTheDumpCanBePinned() {
        let a = id(1), b = id(2), c = id(3)
        let dump = [a, b].map { [$0, "T", "body"].joined(separator: AppleNotesReader.fieldSeparator) }
            .joined(separator: AppleNotesReader.recordSeparator)
        XCTAssertEqual(AppleNotesPins.ids(inDump: dump), [a, b])
        XCTAssertEqual(AppleNotesPins.pinned(among: AppleNotesPins.ids(inDump: dump), keys: [2, 3]), [b])
        XCTAssertFalse(AppleNotesPins.pinned(among: [a, b], keys: [3]).contains(c))
    }

    func testAnUnreadableStoreOrNoAccessIsNilAndNeverAsksAnything() async throws {
        let store = try fixture([(1, 1, 0)])
        let ids = [id(1)]
        let none = await AppleNotesPins.read(ids: ids, home: store, hasAccess: { false },
                                             snapshot: { _ in XCTFail("read without access"); return [1] })
        XCTAssertNil(none)
        let failed = await AppleNotesPins.read(ids: ids, hasAccess: { true }, snapshot: { _ in nil })
        XCTAssertNil(failed)
        let empty = await AppleNotesPins.read(ids: [], hasAccess: { true }, snapshot: { _ in [1] })
        XCTAssertNil(empty)
        let found = await AppleNotesPins.read(ids: ids, hasAccess: { true }, snapshot: { _ in [1] })
        XCTAssertEqual(found, ids)
    }

    func testASlowReadIsLeftBehindAndTheSyncGoesOn() async {
        let started = Date()
        let late = await AppleNotesPins.read(ids: [id(1)], hasAccess: { true },
                                             snapshot: { _ in Thread.sleep(forTimeInterval: 1.5); return [1] },
                                             timeout: 0.2)
        XCTAssertNil(late)
        XCTAssertLessThan(Date().timeIntervalSince(started), 1.2)
    }

    func testTheStoreIsCopiedAndTheCopyReadAndRemoved() throws {
        let store = try fixture([(7, 1, 0)])
        XCTAssertEqual(AppleNotesPins.snapshotKeys(store: store), [7])
        XCTAssertNil(AppleNotesPins.snapshotKeys(store: store.deletingLastPathComponent().appendingPathComponent("gone")))
        let left = (try? FileManager.default.contentsOfDirectory(atPath: FileManager.default.temporaryDirectory.path)) ?? []
        XCTAssertTrue(left.filter { $0.hasPrefix("cicada-notes-pins-") }.isEmpty)
    }

    func testNotesListPinnedFirstUnderTheirOwnHeadingAndNoHeadingWithoutAPin() {
        var pinned = ChannelItem(kind: .episode, id: "a", title: "A")
        pinned.pinned = true
        let plain = ChannelItem(kind: .episode, id: "b", title: "B")
        let split = SourceItemsRules.pinnedSplit([plain, pinned])
        XCTAssertEqual(split?.pinned.map(\.id), ["a"])
        XCTAssertEqual(split?.rest.map(\.id), ["b"])
        XCTAssertNil(SourceItemsRules.pinnedSplit([plain]))
        XCTAssertEqual(Copy.SourcePage.pinned, "Pinned")
    }
}
