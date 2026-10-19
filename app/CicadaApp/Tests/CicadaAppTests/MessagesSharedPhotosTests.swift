import AppKit
import SQLite3
import XCTest
@testable import CicadaApp

/// The photo a chat shares in Messages (owner, 2026-10-16), read from a SYNTHETIC `NickNameCache` folder: a key store
/// with keyed-archive values and PNG avatars, built here. Never the person's real folder.
final class MessagesSharedPhotosTests: XCTestCase {
    private var folder: URL!

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent("NickNameCache-\(UUID().uuidString)",
                                                                               isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: folder) }

    private func archive(_ dict: [String: Any]) throws -> Data {
        try NSKeyedArchiver.archivedData(withRootObject: NSMutableDictionary(dictionary: dict), requiringSecureCoding: false)
    }

    private func png(side: Int) throws -> Data {
        let rep = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side,
                                                 bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                                 colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
        for y in stride(from: 0, to: side, by: 8) { for x in stride(from: 0, to: side, by: 8) {
            rep.setColor(NSColor(red: 0.2, green: 0.6, blue: 0.3, alpha: 1), atX: x, y: y)
        } }
        return try XCTUnwrap(rep.representation(using: .png, properties: [:]))
    }

    private func store(_ rows: [String: Data]) throws {
        var db: OpaquePointer?
        let path = folder.appendingPathComponent(MessagesSharedPhotos.keyStore).path
        XCTAssertEqual(sqlite3_open(path, &db), SQLITE_OK)
        defer { sqlite3_close(db) }
        XCTAssertEqual(sqlite3_exec(db, "CREATE TABLE kvtable (key TEXT PRIMARY KEY, value BLOB)", nil, nil, nil), SQLITE_OK)
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        for (key, value) in rows {
            var stmt: OpaquePointer?
            XCTAssertEqual(sqlite3_prepare_v2(db, "INSERT INTO kvtable VALUES (?1, ?2)", -1, &stmt, nil), SQLITE_OK)
            sqlite3_bind_text(stmt, 1, key, -1, transient)
            _ = value.withUnsafeBytes { sqlite3_bind_blob(stmt, 2, $0.baseAddress, Int32(value.count), transient) }
            XCTAssertEqual(sqlite3_step(stmt), SQLITE_DONE)
            sqlite3_finalize(stmt)
        }
    }

    private func snapshot() throws -> [String: Data] {
        let names = try FileManager.default.contentsOfDirectory(atPath: folder.path)
        return try Dictionary(uniqueKeysWithValues: names.map { ($0, try Data(contentsOf: folder.appendingPathComponent($0))) })
    }

    func testTheSharedPhotoIsFoundByHandleMadeSmallAndNothingIsWritten() throws {
        try png(side: 512).write(to: folder.appendingPathComponent("QUJDREVGR0g==-ad"))
        try store(["+15550000001": archive(["firstName": "Agent", "lastName": "Example", "avatar": "QUJDREVGR0g==-ad"]),
                   "bob@example.com": archive(["firstName": "Bob"])])
        let before = try snapshot()
        let photos = MessagesSharedPhotos.photos(for: ["+15550000001", "bob@example.com", "+15550000009"], folder: folder)
        XCTAssertEqual(Array(photos.keys), ["+15550000001"])
        let image = try XCTUnwrap(NSBitmapImageRep(data: try XCTUnwrap(photos["+15550000001"])))
        XCTAssertLessThanOrEqual(max(image.pixelsWide, image.pixelsHigh), MessagesSharedPhotos.maxPixels)
        XCTAssertEqual(try snapshot(), before, "Messages' folder is only read: no byte changed, no -wal or -shm made")
    }

    /// 2026-10-16 — the watcher posts "shares no photo" as a removal, so "could not look" must never read as it: a
    /// key store that is there but cannot be queried is nil; no key store at all is a definite empty answer.
    func testAnUnreadableKeyStoreIsNilNeverEmpty() throws {
        XCTAssertEqual(MessagesSharedPhotos.photosIfReadable(for: ["+15550000001"], folder: folder), [:])
        try Data("not a database".utf8).write(to: folder.appendingPathComponent(MessagesSharedPhotos.keyStore))
        XCTAssertNil(MessagesSharedPhotos.photosIfReadable(for: ["+15550000001"], folder: folder))
        XCTAssertEqual(MessagesSharedPhotos.photos(for: ["+15550000001"], folder: folder), [:], "the bubbles' answer")
    }

    func testOnlyTheAskedHandlesAreLookedUp() throws {
        try png(side: 64).write(to: folder.appendingPathComponent("WFla==-ad"))
        try store(["+15550000001": archive(["avatar": "WFla==-ad"]), "+15550000003": archive(["avatar": "WFla==-ad"])])
        XCTAssertEqual(Array(MessagesSharedPhotos.photos(for: ["+15550000003"], folder: folder).keys), ["+15550000003"])
        XCTAssertTrue(MessagesSharedPhotos.photos(for: [], folder: folder).isEmpty)
    }

    func testANameThatLeavesTheFolderOrIsNotAnAvatarIsRefused() throws {
        let outside = folder.deletingLastPathComponent().appendingPathComponent("outside-\(UUID().uuidString)-ad")
        try png(side: 64).write(to: outside)
        defer { try? FileManager.default.removeItem(at: outside) }
        try FileManager.default.createSymbolicLink(at: folder.appendingPathComponent("link-ad"), withDestinationURL: outside)
        try png(side: 64).write(to: folder.appendingPathComponent("plain.png"))
        try store(["a": archive(["avatar": "../\(outside.lastPathComponent)"]),
                   "b": archive(["avatar": "link-ad"]),
                   "c": archive(["avatar": "plain.png"]),
                   "d": Data("not an archive".utf8)])
        XCTAssertTrue(MessagesSharedPhotos.photos(for: ["a", "b", "c", "d"], folder: folder).isEmpty)
        XCTAssertFalse(MessagesSharedPhotos.isAvatarName("-ad"))
        XCTAssertFalse(MessagesSharedPhotos.isAvatarName(".hidden-ad"))
    }

    /// 2026-10-19 — the record as the current macOS writes it (measured, values redacted): the avatar is an ABSOLUTE
    /// `imageFilePath` inside a nested `NickNameImage` dictionary, the file named with "_" where the record's `rid`
    /// carries "/". Every real record yielded nil while only a bare file name was accepted.
    func testTheCurrentRecordShapeAnAbsolutePathInANestedDictionaryResolves() throws {
        let file = "QUJD_REVGR0g==-ad"
        try png(side: 256).write(to: folder.appendingPathComponent(file))
        let image: [String: Any] = ["imageFilePath": folder.appendingPathComponent(file).path,
                                    "contentIsSensitive": false, "imageName": "QUJD/REVGR0g=="]
        try store(["+15550000001": archive(["rid": "QUJD/REVGR0g==", "firstName": "Agent",
                                            "NickNameImage": NSMutableDictionary(dictionary: image)])])
        XCTAssertEqual(MessagesSharedPhotos.avatarNames(for: ["+15550000001"], folder: folder), ["+15550000001": file])
        let photos = MessagesSharedPhotos.photos(for: ["+15550000001"], folder: folder)
        XCTAssertEqual(Array(photos.keys), ["+15550000001"])
        let small = try XCTUnwrap(NSBitmapImageRep(data: try XCTUnwrap(photos["+15550000001"])))
        XCTAssertLessThanOrEqual(max(small.pixelsWide, small.pixelsHigh), MessagesSharedPhotos.maxPixels)
    }

    /// An absolute path is used only when its parent is exactly the folder: never one elsewhere, never one that climbs
    /// out with `..`, and never through a link — `avatarFile`'s checks still apply to the name it yields.
    func testAnAbsolutePathOutsideTheFolderIsRefused() throws {
        let elsewhere = folder.deletingLastPathComponent().appendingPathComponent("elsewhere-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: elsewhere, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: elsewhere) }
        try png(side: 64).write(to: elsewhere.appendingPathComponent("WFla==-ad"))
        try FileManager.default.createSymbolicLink(at: folder.appendingPathComponent("bGluaw==-ad"),
                                                   withDestinationURL: elsewhere.appendingPathComponent("WFla==-ad"))
        let climb = folder.path + "/../" + elsewhere.lastPathComponent + "/WFla==-ad"
        try store(["a": archive(["NickNameImage": NSMutableDictionary(dictionary:
                                    ["imageFilePath": elsewhere.appendingPathComponent("WFla==-ad").path])]),
                   "b": archive(["NickNameImage": NSMutableDictionary(dictionary: ["imageFilePath": climb])]),
                   "c": archive(["NickNameImage": NSMutableDictionary(dictionary:
                                    ["imageFilePath": folder.appendingPathComponent("bGluaw==-ad").path])]),
                   "d": archive(["NickNameImage": NSMutableDictionary(dictionary: ["imageFilePath": "NickNameCache/WFla==-ad"])])])
        XCTAssertTrue(MessagesSharedPhotos.photos(for: ["a", "b", "c", "d"], folder: folder).isEmpty)
        XCTAssertNil(MessagesSharedPhotos.folderFileName(climb, in: folder))
        XCTAssertNil(MessagesSharedPhotos.folderFileName("relative/WFla==-ad", in: folder))
    }

    func testAMissingFolderIsNoPhoto() {
        XCTAssertTrue(MessagesSharedPhotos.photos(for: ["+15550000001"],
                                                  folder: folder.appendingPathComponent("absent")).isEmpty)
    }
}
