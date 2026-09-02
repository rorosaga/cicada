import XCTest
@testable import CicadaApp

/// R1/R9 — the app reads the browser files (it is what the user grants Full
/// Disk Access to); an unreadable file names the exact fix.
final class BrowserFilesTests: XCTestCase {

    func testSafariTabsPrefersTheContainerPathThenTheLegacyOne() {
        let paths = BrowserFile.safariTabsDb.candidatePaths.map(\.path)
        XCTAssertEqual(paths.count, 2)
        XCTAssertTrue(paths[0].hasSuffix("/Library/Containers/com.apple.Safari/Data/Library/Safari/CloudTabs.db"))
        XCTAssertTrue(paths[1].hasSuffix("/Library/Safari/CloudTabs.db"))
        XCTAssertTrue(BrowserFile.safariTabsWal.candidatePaths.allSatisfy { $0.path.hasSuffix("CloudTabs.db-wal") })
        XCTAssertTrue(BrowserFile.safariBookmarks.candidatePaths[0].path.hasSuffix("/Library/Safari/Bookmarks.plist"))
        XCTAssertTrue(BrowserFile.chromeBookmarks.candidatePaths[0].path.hasSuffix("/Library/Application Support/Google/Chrome/Default/Bookmarks"))
    }

    func testNoPermissionBecomesNotReadableWithTheFullDiskAccessFix() {
        let err = NSError(domain: NSCocoaErrorDomain, code: NSFileReadNoPermissionError)
        let classified = BrowserFileError.classify(err, file: .safariTabsDb, path: "/x/CloudTabs.db")
        XCTAssertEqual(classified, .notReadable(.safariTabsDb, "/x/CloudTabs.db"))
        XCTAssertTrue(classified.userMessage.contains("Full Disk Access"))
        XCTAssertTrue(classified.userMessage.contains("System Settings → Privacy & Security → Full Disk Access → Cicada"))
        XCTAssertEqual(BrowserFileError.fullDiskAccessURL.absoluteString,
                       "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")
    }

    func testMissingFileIsNotAPermissionProblem() {
        let err = NSError(domain: NSCocoaErrorDomain, code: NSFileReadNoSuchFileError)
        let classified = BrowserFileError.classify(err, file: .safariTabsDb, path: "/x/CloudTabs.db")
        XCTAssertEqual(classified, .missing(.safariTabsDb, ["/x/CloudTabs.db"]))
        XCTAssertFalse(classified.userMessage.contains("Full Disk Access"))
        XCTAssertTrue(classified.userMessage.contains("iCloud tabs"))
    }

    /// A POSIX ENOENT (what `Data(contentsOf:)` surfaces on some paths) is the
    /// same "nothing here yet" as the Cocoa no-such-file code — never a
    /// permission fix.
    func testPosixEnoentIsAlsoMissing() {
        let err = NSError(domain: NSPOSIXErrorDomain, code: Int(ENOENT))
        let classified = BrowserFileError.classify(err, file: .chromeBookmarks, path: "/x/Bookmarks")
        XCTAssertEqual(classified, .missing(.chromeBookmarks, ["/x/Bookmarks"]))
    }

    /// The Feed strip's "Sync now" never pattern-matches this type: it hands
    /// the thrown error to `AddSourceSheet.friendlyError`, whose fallback is
    /// `localizedDescription`. That fallback must be the R9 sentence, not
    /// Foundation's "The operation couldn't be completed" (review round 1, H1).
    func testFriendlyErrorSurfacesTheFullDiskAccessFixForAStripSync() {
        let error = BrowserFileError.notReadable(.safariBookmarks, "/x")
        XCTAssertEqual(AddSourceSheet.friendlyError(error), error.userMessage)
        XCTAssertEqual(AddSourceSheet.friendlyError(error), error.localizedDescription)
        XCTAssertTrue(AddSourceSheet.friendlyError(error).contains("Full Disk Access"))
        let missing = BrowserFileError.missing(.safariTabsDb, ["/x"])
        XCTAssertEqual(AddSourceSheet.friendlyError(missing), missing.userMessage)
    }

    func testReadIfPresentReturnsNilForAMissingSidecar() async throws {
        // Every candidate path lives under the real home; the WAL sidecar is
        // the one file that legitimately may not exist. Only a genuine
        // absence becomes nil.
        let data = try await BrowserFileReader.readIfPresent(.safariTabsWal, candidates: [URL(fileURLWithPath: "/nonexistent/CloudTabs.db-wal")])
        XCTAssertNil(data)
    }

    func testReadIfPresentReturnsTheBytesWhenTheSidecarExists() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let wal = dir.appendingPathComponent("CloudTabs.db-wal")
        try Data("wal-bytes".utf8).write(to: wal)
        let data = try await BrowserFileReader.readIfPresent(.safariTabsWal, candidates: [dir.appendingPathComponent("missing"), wal])
        XCTAssertEqual(data.map { String(decoding: $0, as: UTF8.self) }, "wal-bytes")
    }

    /// A sidecar Cicada is DENIED is not a sidecar that is absent: the old
    /// `fileExists` pre-filter answered false for both and silently imported
    /// without the WAL. Now the permission failure propagates with the fix
    /// (review round 1, L2).
    func testReadIfPresentDoesNotSwallowAPermissionFailure() async throws {
        try XCTSkipIf(geteuid() == 0, "root is never denied by mode bits")
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let wal = dir.appendingPathComponent("CloudTabs.db-wal")
        try Data("secret".utf8).write(to: wal)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: wal.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: wal.path) }
        do {
            _ = try await BrowserFileReader.readIfPresent(.safariTabsWal, candidates: [wal])
            XCTFail("expected a throw")
        } catch let e as BrowserFileError {
            XCTAssertEqual(e, .notReadable(.safariTabsWal, wal.path))
        }
    }

    /// `read` walks the candidates in order and reports a MISSING error
    /// naming every path it tried, so the user sees where Cicada looked.
    func testReadReportsEveryCandidateWhenAllAreMissing() async {
        let urls = [URL(fileURLWithPath: "/nonexistent/a/CloudTabs.db"),
                    URL(fileURLWithPath: "/nonexistent/b/CloudTabs.db")]
        do {
            _ = try await BrowserFileReader.read(.safariTabsDb, candidates: urls)
            XCTFail("expected a throw")
        } catch let e as BrowserFileError {
            XCTAssertEqual(e, .missing(.safariTabsDb, urls.map(\.path)))
        } catch {
            XCTFail("unexpected error \(error)")
        }
    }

    /// The second candidate is the one that exists — `read` must reach it.
    func testReadFallsThroughToALaterCandidate() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let real = dir.appendingPathComponent("Bookmarks")
        try Data("synthetic".utf8).write(to: real)
        let data = try await BrowserFileReader.read(
            .chromeBookmarks, candidates: [dir.appendingPathComponent("missing"), real])
        XCTAssertEqual(String(decoding: data, as: UTF8.self), "synthetic")
    }
}
