import CoreGraphics
import Foundation
import ImageIO
import SQLite3
import UniformTypeIdentifiers
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

    // MARK: Ruling 61 — Apple Books' own covers

    private func writeCover(asset: String, name: String, side: Int = 40) throws -> URL {
        let folder = dir.appendingPathComponent(asset, isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let url = folder.appendingPathComponent(name)
        let context = CGContext(data: nil, width: side, height: side * 3 / 2, bitsPerComponent: 8, bytesPerRow: 0,
                                space: CGColorSpaceCreateDeviceRGB(),
                                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        context.setFillColor(CGColor(red: 0.2, green: 0.3, blue: 0.4, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: side, height: side * 3 / 2))
        let target = CGImageDestinationCreateWithURL(url as CFURL, UTType.jpeg.identifier as CFString, 1, nil)!
        CGImageDestinationAddImage(target, context.makeImage()!, nil)
        XCTAssertTrue(CGImageDestinationFinalize(target))
        return url
    }

    func testTheCoverCacheSitsBesideDocumentsInTheSameContainer() {
        let documents = URL(fileURLWithPath: "/h/Library/Containers/com.apple.iBooksX/Data/Documents", isDirectory: true)
        XCTAssertEqual(AppleBooksCovers.folder(documents: documents).path,
                       "/h/Library/Containers/com.apple.iBooksX/Data/Library/Caches/BCCoverCache-1/BICDiskDataStore")
    }

    func testTheLargestReadablePictureIsChosenAndTheTexturesNever() throws {
        _ = try writeCover(asset: "A1", name: "A1|1|200|312|0.jpg")
        let large = try writeCover(asset: "A1", name: "A1|1|792|1024|0.jpg")
        try Data("astc".utf8).write(to: dir.appendingPathComponent("A1/A1|1|1000|2000|580.astc"))
        XCTAssertEqual(AppleBooksCovers.bestFile(asset: "A1", in: dir)?.lastPathComponent, large.lastPathComponent)
        XCTAssertNil(AppleBooksCovers.bestFile(asset: "none", in: dir))
    }

    func testAnAssetIdNeverWalksOutOfTheCache() {
        for bad in ["", "../x", "a/b", "..", ".hidden", "a\\b"] {
            XCTAssertFalse(AppleBooksCovers.isPathSafe(bad), bad)
            XCTAssertNil(AppleBooksCovers.bestFile(asset: bad, in: dir), bad)
        }
        XCTAssertTrue(AppleBooksCovers.isPathSafe("1234567890"))
        XCTAssertTrue(AppleBooksCovers.isPathSafe("ABCDEF0123456789ABCDEF0123456789"))
    }

    func testOnlyBooksTheLibraryShowsGetACover() {
        func record(_ id: String, type: Int?, hidden: Bool = false) -> AppleBooksBookRecord {
            AppleBooksBookRecord(assetId: id, contentType: type, isFinished: false, isHidden: hidden, annotations: [])
        }
        let books = [record("A1", type: 1), record("A2", type: nil), record("A3", type: 3), record("A4", type: 5),
                     record("A5", type: 1, hidden: true)]
        XCTAssertEqual(AppleBooksCovers.assets(of: books), ["A1", "A2"])
    }

    func testACoverIsDrawnDownToASmallJpegAndOnlyWhatChangedIsSentAgain() throws {
        let file = try writeCover(asset: "A1", name: "A1|1|800|1200|0.jpg", side: 800)
        let data = try XCTUnwrap(AppleBooksCovers.jpeg(file))
        XCTAssertLessThanOrEqual(data.count, AppleBooksCovers.maxBytes)
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))
        let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
        XCTAssertLessThanOrEqual(max(image.width, image.height), Int(AppleBooksCovers.longestSide))

        let first = AppleBooksCovers.unsent(assets: ["A1", "none"], folder: dir, sent: [:])
        XCTAssertEqual(first.map(\.0), ["A1"])
        let second = AppleBooksCovers.unsent(assets: ["A1"], folder: dir, sent: ["A1": first[0].1])
        XCTAssertTrue(second.isEmpty)
    }

    func testATallThumbnailIsDrawnWholeInItsWellAndAWideOneFillsIt() {
        let well = CGSize(width: 60, height: 40)
        let cover = EntityPictureLayout.drawnFrame(.media, source: .thumbnail, image: CGSize(width: 200, height: 300),
                                                   well: well)
        XCTAssertEqual(cover, CGSize(width: 27, height: 40))
        XCTAssertEqual(EntityPictureLayout.drawnFrame(.media, source: .thumbnail, image: CGSize(width: 300, height: 200),
                                                      well: well), well)
        XCTAssertEqual(EntityPictureLayout.drawnFrame(.media, source: .upload, image: CGSize(width: 200, height: 300),
                                                      well: well), well)
        XCTAssertEqual(EntityPictureLayout.drawnFrame(.media, source: .thumbnail, image: nil, well: well), well)
    }

    func testABooksStatusLineSaysItOnce() {
        let chat = BookStatusRecord(status: "finished", day: "2026-10-20", claimId: "c", fromChat: true)
        let door = BookStatusRecord(status: "reading", day: nil, claimId: "c", fromChat: false)
        let locale = Locale(identifier: "en_GB")
        XCTAssertTrue(BooksRowText.status(chat, locale: locale).hasPrefix("Finished · "))
        XCTAssertTrue(BooksRowText.status(chat, locale: locale).hasSuffix(" · " + Copy.bookStatusFromChat))
        XCTAssertEqual(BooksRowText.status(door, locale: locale), "Reading now")
    }

    func testABookRowDecodesItsCoverAndAnOlderBackendSendsNone() throws {
        let raw = #"{"kind":"page","id":"b","title":"T","book":true,"cover":"/entities/b/preview?v=abcdef012345"}"#
        let row = try JSONDecoder().decode(ChannelItem.self, from: Data(raw.utf8))
        XCTAssertEqual(row.book, true)
        XCTAssertEqual(row.cover, "/entities/b/preview?v=abcdef012345")
        let old = try JSONDecoder().decode(ChannelItem.self, from: Data(#"{"kind":"page","id":"b","title":"T"}"#.utf8))
        XCTAssertNil(old.book)
        XCTAssertNil(old.cover)
    }

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
        XCTAssertNotNil(try AppleBooksPaths.library(in: dir))
        XCTAssertNotNil(try AppleBooksPaths.annotations(in: dir))
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

    /// ROR-41: a folder the system refuses to list is the permission fix, never "Open Apple Books once".
    func testARefusedLibraryFolderIsTheExactFixNeverNotInstalled() throws {
        let folder = dir.appendingPathComponent("BKLibrary", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: folder.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: folder.path) }
        XCTAssertThrowsError(try AppleBooksStore.snapshot(documents: dir)) { error in
            guard case BrowserFileError.notReadable(.appleBooksLibrary, _) = error else {
                return XCTFail("a refusal read as \(error)")
            }
            XCTAssertTrue((error as? BrowserFileError)?.userMessage.contains("Full Disk Access") == true)
        }
    }

    func testARefusedStoreFileIsTheExactFixToo() throws {
        makeStores()
        let store = try XCTUnwrap(try AppleBooksPaths.library(in: dir))
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: store.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: store.path) }
        XCTAssertThrowsError(try AppleBooksStore.snapshot(documents: dir)) { error in
            guard case BrowserFileError.notReadable(.appleBooksLibrary, _) = error else {
                return XCTFail("a refusal read as \(error)")
            }
        }
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

    func testANewBookWaitsForTheChoiceAndAKnownOneIsKeptCurrent() {
        func book(_ id: String, hidden: Bool = false, progress: Double = 0) -> AppleBooksBookRecord {
            AppleBooksBookRecord(assetId: id, title: id, author: nil, epubId: nil, contentType: 1, isFinished: false,
                                 isHidden: hidden, progress: progress, finishedAt: nil, lastOpenedAt: nil, addedAt: nil,
                                 annotations: [])
        }
        let known = book("known", progress: 0.2), changed = book("known", progress: 0.5)
        let sent = ["known": AppleBooksStore.fingerprint(known)]
        let a = AppleBooksStore.partition([changed, book("new"), book("declined"), book("hid", hidden: true)],
                                          sent: sent, skipped: ["declined"])
        XCTAssertEqual(a.fresh.map(\.assetId), ["new"])
        XCTAssertEqual(a.update.map(\.assetId), [])  // page turns alone are no change
        let b = AppleBooksStore.partition([known], sent: sent, skipped: [])
        XCTAssertTrue(b.fresh.isEmpty && b.update.isEmpty)
    }

    func testThePageLineSaysWhatCameIn() {
        let now = Date()
        let en = Locale(identifier: "en_US")
        XCTAssertNil(BooksRowText.appleBooks(.off))
        XCTAssertEqual(BooksRowText.appleBooks(.syncing), .init(text: Copy.appleBooksSyncing))
        XCTAssertEqual(BooksRowText.appleBooks(.failed("why")), .init(text: "why", isProblem: true))
        XCTAssertEqual(BooksRowText.appleBooks(.synced(at: now, books: 284, highlights: 1, notKept: 0), locale: en),
                       .init(text: "284 books · 1 highlight"))
        // Re-check of #600: what a book's cap left out is said on the page's one line, never silent.
        XCTAssertEqual(BooksRowText.appleBooks(.synced(at: now, books: 2, highlights: 3000, notKept: 26), locale: en),
                       .init(text: "2 books · 3,000 highlights · 26 highlights past a book's limit not kept"))
        // A read the backend refused outranks the counts, as the one thing to fix.
        XCTAssertEqual(BooksRowText.appleBooks(.synced(at: now, books: 2, highlights: 1, notKept: 0), lastError: "bad"),
                       .init(text: "bad", isProblem: true))
        let preview = GoodreadsPreview(books: 3, finished: 1, reading: 1, want: 1, reviews: 1, rated: 1)
        XCTAssertEqual(BooksRowText.goodreadsPreview(preview, locale: en),
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

    func testReadingIsItsOwnSectionWithAppleBooksGoodreadsAndBookScans() {
        let entries = SourceCatalog.fixed.filter { $0.group == .reading }
        XCTAssertEqual(entries.map(\.id), [AppleBooksReader.channel, "goodreads", "book-scan"])
        XCTAssertEqual(SourceCategory.reading.title, "Reading")
        XCTAssertNotNil(SourceCatalog.exportHow("goodreads"))
        XCTAssertEqual(SourceKind.order.firstIndex(of: .reading).map { $0 + 1 }, SourceKind.order.firstIndex(of: .import))
    }
}
