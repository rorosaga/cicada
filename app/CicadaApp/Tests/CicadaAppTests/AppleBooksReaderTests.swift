import Foundation
import SQLite3
import XCTest
@testable import CicadaApp

/// G39 — the Apple Books reader: the two stores found by prefix, copied with their WAL and read read-only, only the
/// whitelisted columns, highlights only (never a bookmark or the reading position), deleted ones dropped, and only the
/// books that changed sent again. Synthetic stores built here with the real table and column names; placeholder text.
final class AppleBooksReaderTests: XCTestCase {
    private var dir: URL!

    override func setUpWithError() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("ab-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir.appendingPathComponent("BKLibrary"), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: dir.appendingPathComponent("AEAnnotation"), withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: dir) }

    private func exec(_ url: URL, _ sql: [String]) {
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(url.path, &db), SQLITE_OK)
        for statement in sql { XCTAssertEqual(sqlite3_exec(db, statement, nil, nil, nil), SQLITE_OK, statement) }
        sqlite3_close(db)
    }

    private func makeStores() {
        exec(dir.appendingPathComponent("BKLibrary/BKLibrary-1-091020131601.sqlite"), [
            "PRAGMA journal_mode=WAL",
            "CREATE TABLE ZBKLIBRARYASSET (Z_PK INTEGER PRIMARY KEY, ZASSETID VARCHAR, ZTITLE VARCHAR, ZAUTHOR VARCHAR, "
                + "ZEPUBID VARCHAR, ZCONTENTTYPE INTEGER, ZISFINISHED INTEGER, ZDATEFINISHED TIMESTAMP, "
                + "ZREADINGPROGRESS FLOAT, ZLASTOPENDATE TIMESTAMP, ZCREATIONDATE TIMESTAMP, ZISHIDDEN INTEGER, "
                + "ZPURCHASEDDSID VARCHAR, ZBOOKDESCRIPTION VARCHAR)",
            "INSERT INTO ZBKLIBRARYASSET VALUES (1, 'A1', 'The Lantern Orchard', 'Ada Example', "
                + "'urn:isbn:9780000000002', 1, 1, 810000000, 1.0, 810000000, 700000000, 0, 'secret-account', 'blurb')",
            "INSERT INTO ZBKLIBRARYASSET VALUES (2, 'A2', 'Quiet Engines', 'Bea Sample', NULL, 1, 0, NULL, 0.4, "
                + "805000000, 700000000, 0, NULL, NULL)",
        ])
        exec(dir.appendingPathComponent("AEAnnotation/AEAnnotation_v10312011_1727_local.sqlite"), [
            "PRAGMA journal_mode=WAL",
            "CREATE TABLE ZAEANNOTATION (Z_PK INTEGER PRIMARY KEY, ZANNOTATIONASSETID VARCHAR, ZANNOTATIONUUID VARCHAR, "
                + "ZANNOTATIONTYPE INTEGER, ZANNOTATIONSELECTEDTEXT VARCHAR, ZANNOTATIONNOTE VARCHAR, "
                + "ZANNOTATIONDELETED INTEGER, ZANNOTATIONCREATIONDATE TIMESTAMP, ZANNOTATIONLOCATION VARCHAR)",
            "INSERT INTO ZAEANNOTATION VALUES (1, 'A1', 'u2', 2, 'Second highlight.', NULL, 0, 809000100, 'cfi')",
            "INSERT INTO ZAEANNOTATION VALUES (2, 'A1', 'u1', 2, 'First highlight.', 'My own note.', 0, 809000000, 'cfi')",
            "INSERT INTO ZAEANNOTATION VALUES (3, 'A1', 'u3', 2, 'Deleted one.', NULL, 1, 809000200, 'cfi')",
            "INSERT INTO ZAEANNOTATION VALUES (4, 'A1', 'u4', 3, NULL, NULL, 0, 809000300, 'position')",
            "INSERT INTO ZAEANNOTATION VALUES (5, 'A1', 'u5', 1, NULL, NULL, 0, 809000400, 'bookmark')",
        ])
    }

    func testTheStoresAreFoundByPrefixAndReadFromACopy() throws {
        makeStores()
        XCTAssertNotNil(AppleBooksPaths.library(in: dir))
        XCTAssertNotNil(AppleBooksPaths.annotations(in: dir))
        let books = try AppleBooksStore.snapshot(documents: dir)
        XCTAssertEqual(books.map(\.assetId).sorted(), ["A1", "A2"])
        let lantern = try XCTUnwrap(books.first { $0.assetId == "A1" })
        XCTAssertTrue(lantern.isFinished)
        XCTAssertEqual(lantern.epubId, "urn:isbn:9780000000002")
        // Highlights only, oldest first, the deleted one and the bookmark and position never read.
        XCTAssertEqual(lantern.annotations.map(\.selectedText), ["First highlight.", "Second highlight."])
        XCTAssertEqual(lantern.annotations.first?.note, "My own note.")
        // Core Data dates are seconds since 2001-01-01.
        XCTAssertEqual(lantern.addedAt, ISO8601DateFormatter().string(from: Date(timeIntervalSinceReferenceDate: 700_000_000)))
        // Nothing outside the whitelist reaches the payload.
        let json = String(data: try JSONEncoder().encode(AppleBooksSyncPayload(books: books)), encoding: .utf8) ?? ""
        XCTAssertFalse(json.contains("secret-account"))
        XCTAssertFalse(json.contains("blurb"))
        XCTAssertFalse(json.contains("cfi"))
        // The copy is gone.
        let leftovers = try FileManager.default.contentsOfDirectory(atPath: FileManager.default.temporaryDirectory.path)
            .filter { $0.hasPrefix("cicada-apple-books-") }
        XCTAssertTrue(leftovers.isEmpty)
    }

    func testAMissingLibraryIsSaidInWords() {
        XCTAssertThrowsError(try AppleBooksStore.snapshot(documents: dir)) { error in
            XCTAssertEqual(error as? AppleBooksReadError, .notInstalled)
        }
    }

    func testOnlyBooksThatChangedAreSentAgainAndProgressAloneIsNoChange() throws {
        makeStores()
        let books = try AppleBooksStore.snapshot(documents: dir)
        var sent: [String: String] = [:]
        XCTAssertEqual(AppleBooksStore.changed(books, sent: sent).count, 2)
        for book in books { sent[book.assetId] = AppleBooksStore.fingerprint(book) }
        XCTAssertTrue(AppleBooksStore.changed(books, sent: sent).isEmpty)
        var moved = books
        if let i = moved.firstIndex(where: { $0.assetId == "A2" }) {
            moved[i].progress = 0.55            // a page turned: not a change worth a post
            moved[i].lastOpenedAt = "2026-11-04T08:00:00Z"
        }
        XCTAssertTrue(AppleBooksStore.changed(moved, sent: sent).isEmpty)
        if let i = moved.firstIndex(where: { $0.assetId == "A1" }) {
            moved[i].annotations.append(AppleBooksAnnotationRecord(uuid: "u9", createdAt: "2026-11-04T08:00:00Z",
                                                                   selectedText: "New one.", note: nil))
        }
        XCTAssertEqual(AppleBooksStore.changed(moved, sent: sent).map(\.assetId), ["A1"])
    }

    func testTheRowSaysWhatCameIn() {
        let now = Date()
        XCTAssertEqual(BooksRowText.appleBooks(.off, now: now), Copy.appleBooksOff)
        let line = BooksRowText.appleBooks(.synced(at: now, books: 284, highlights: 1, notKept: 0), now: now,
                                           locale: Locale(identifier: "en_US"))
        XCTAssertTrue(line.hasSuffix("· 284 books · 1 highlight"), line)
        // Re-check of #600: what a book's cap left out is said on the row, never silent.
        let over = BooksRowText.appleBooks(.synced(at: now, books: 2, highlights: 3000, notKept: 26), now: now,
                                           locale: Locale(identifier: "en_US"))
        XCTAssertTrue(over.hasSuffix("· 3,000 highlights · 26 highlights past a book's limit not kept"), over)
        let preview = GoodreadsPreview(books: 3, finished: 1, reading: 1, want: 1, reviews: 1, rated: 1)
        XCTAssertEqual(BooksRowText.goodreadsPreview(preview, locale: Locale(identifier: "en_US")),
                       "3 books: 1 finished · 1 reading · 1 want to read · 1 review")
    }

    func testTheSyncAnswerCarriesWhatACapLeftOutPerBook() throws {
        let json = #"{"books": 1, "created": 1, "updated": 0, "unchanged": 0, "highlights": 3000, "notes": 0, "#
            + #""trimmed": 25, "trimmedBooks": {"CAP": 25}}"#
        let result = try JSONDecoder().decode(AppleBooksSyncResult.self, from: Data(json.utf8))
        XCTAssertEqual(result.trimmedBooks, ["CAP": 25])
        let older = #"{"books": 1, "created": 1, "updated": 0, "unchanged": 0, "highlights": 1, "notes": 0}"#
        XCTAssertNil(try JSONDecoder().decode(AppleBooksSyncResult.self, from: Data(older.utf8)).trimmedBooks)
    }

    func testReadingIsItsOwnSectionWithAppleBooksAndGoodreads() {
        let entries = SourceCatalog.fixed.filter { $0.group == .reading }
        XCTAssertEqual(entries.map(\.id), [AppleBooksReader.channel, "goodreads"])
        XCTAssertEqual(SourceCatalogGroup.reading.title, "Reading")
        XCTAssertNotNil(SourceCatalog.exportHow("goodreads"))
        XCTAssertEqual(SourceKind.order.firstIndex(of: .reading).map { $0 + 1 }, SourceKind.order.firstIndex(of: .import))
    }
}
