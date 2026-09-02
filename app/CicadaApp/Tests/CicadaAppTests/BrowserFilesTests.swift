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

    func testReadIfPresentReturnsNilForAMissingSidecar() async {
        // Every candidate path lives under the real home; the WAL sidecar is
        // the one file that legitimately may not exist. A permission failure
        // here must NOT be swallowed into nil — only a genuine absence.
        let data = await BrowserFileReader.readIfPresent(.safariTabsWal, candidates: [URL(fileURLWithPath: "/nonexistent/CloudTabs.db-wal")])
        XCTAssertNil(data)
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
