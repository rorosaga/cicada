import XCTest
@testable import CicadaApp

/// Issue #7 — the app lists a location page's folder; the backend only names the path.
final class LocationListerTests: XCTestCase {
    /// The seam: a canned listing, or the error the system would throw.
    private struct Fake: LocationLister.FileSystem {
        var entries: [LocationLister.RawEntry] = []
        var error: NSError?
        var seen: (@Sendable (String) -> Void)?

        func contents(ofDirectory path: String) throws -> [LocationLister.RawEntry] {
            seen?(path)
            if let error { throw error }
            return entries
        }
    }

    private final class Box: @unchecked Sendable { var value: String? }

    private func refusal(_ ns: NSError) -> LocationListing {
        LocationLister.listNow("~/src/alpha-project", fileSystem: Fake(error: ns))
    }

    // MARK: listing and ordering

    func testDirectoriesComeFirstThenNamesCaseInsensitively() {
        let fake = Fake(entries: [
            .init(name: "b.md", isDir: false, size: 42),
            .init(name: "Zeta", isDir: true, size: 0),
            .init(name: "A.txt", isDir: false, size: 5),
            .init(name: "alpha", isDir: true, size: 0),
            .init(name: ".hidden", isDir: false, size: 1),
        ])
        let listing = LocationLister.listNow("/Users/example/src/alpha-project", fileSystem: fake)
        XCTAssertEqual(listing.path, "/Users/example/src/alpha-project")
        XCTAssertTrue(listing.exists)
        XCTAssertTrue(listing.accessible)
        XCTAssertFalse(listing.truncated)
        // Hidden entries are listed, as the backend's scandir listed them.
        XCTAssertEqual(listing.entries.map(\.name), ["alpha", "Zeta", ".hidden", "A.txt", "b.md"])
        XCTAssertEqual(listing.entries.first { $0.name == "b.md" }?.size, 42)
    }

    func testTheListingIsCappedAndSaysSo() {
        let fake = Fake(entries: (0..<250).map { .init(name: String(format: "f%03d.txt", $0), isDir: false, size: 1) })
        let listing = LocationLister.listNow("/tmp/many", fileSystem: fake)
        XCTAssertEqual(listing.entries.count, LocationLister.maxEntries)
        XCTAssertTrue(listing.truncated)
        XCTAssertEqual(listing.entries.first?.name, "f000.txt")
    }

    func testTheCapKeepsDirectoriesFirst() {
        let files = (0..<199).map { LocationLister.RawEntry(name: "f\($0)", isDir: false, size: 1) }
        let dirs = (0..<3).map { LocationLister.RawEntry(name: "z\($0)", isDir: true, size: 0) }
        let listing = LocationLister.listNow("/tmp/mixed", fileSystem: Fake(entries: files + dirs))
        XCTAssertEqual(Array(listing.entries.prefix(3)).map(\.name), ["z0", "z1", "z2"])
        XCTAssertTrue(listing.truncated)
    }

    // MARK: tilde

    func testATildePathIsExpandedToHomeAndKeptAsDeclared() {
        let box = Box()
        let fake = Fake(seen: { box.value = $0 })
        let listing = LocationLister.listNow("~/src/alpha-project", fileSystem: fake)
        XCTAssertEqual(box.value, NSHomeDirectory() + "/src/alpha-project")
        XCTAssertEqual(listing.path, "~/src/alpha-project")
    }

    func testARelativePathIsNeverListed() {
        let box = Box()
        let listing = LocationLister.listNow("src/alpha-project", fileSystem: Fake(seen: { box.value = $0 }))
        XCTAssertNil(box.value)
        XCTAssertFalse(listing.exists)
    }

    // MARK: ENOENT vs EPERM

    func testAMissingFolderIsNotFound() {
        for ns in [NSError(domain: NSCocoaErrorDomain, code: NSFileReadNoSuchFileError),
                   NSError(domain: NSPOSIXErrorDomain, code: Int(ENOENT)),
                   NSError(domain: NSCocoaErrorDomain, code: NSFileReadUnknownError,
                           userInfo: [NSUnderlyingErrorKey: NSError(domain: NSPOSIXErrorDomain, code: Int(ENOTDIR))])] {
            let listing = refusal(ns)
            XCTAssertFalse(listing.exists, "\(ns)")
            XCTAssertTrue(listing.entries.isEmpty)
        }
    }

    func testAPermissionDenialIsNeverNotFound() {
        for ns in [NSError(domain: NSCocoaErrorDomain, code: NSFileReadNoPermissionError),
                   NSError(domain: NSPOSIXErrorDomain, code: Int(EPERM)),
                   NSError(domain: NSPOSIXErrorDomain, code: Int(EACCES)),
                   NSError(domain: NSCocoaErrorDomain, code: NSFileReadUnknownError,
                           userInfo: [NSUnderlyingErrorKey: NSError(domain: NSPOSIXErrorDomain, code: Int(EPERM))])] {
            let listing = refusal(ns)
            XCTAssertTrue(listing.exists, "\(ns)")
            XCTAssertFalse(listing.accessible, "\(ns)")
            XCTAssertTrue(listing.entries.isEmpty)
        }
    }

    func testTheDenialSentenceNamesWhereToAllowIt() {
        XCTAssertTrue(Copy.Graph.folderNotAllowed.contains("Privacy & Security → Files and Folders"))
        XCTAssertFalse(Copy.Graph.folderNotAllowed.lowercased().contains("not found"))
    }

    // MARK: the real disk

    func testTheDiskListsAFolderWithoutFollowingASymlink() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("LocationListerTests-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root.appendingPathComponent("subdir"), withIntermediateDirectories: true)
        try "hello".write(to: root.appendingPathComponent("a.txt"), atomically: true, encoding: .utf8)
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent("link"),
                                                   withDestinationURL: root.appendingPathComponent("subdir"))

        let listing = await LocationLister.list(root.path)
        XCTAssertTrue(listing.exists)
        XCTAssertTrue(listing.accessible)
        XCTAssertEqual(listing.entries.map(\.name), ["subdir", "a.txt", "link"])
        XCTAssertEqual(listing.entries.first { $0.name == "a.txt" }?.size, 5)
        XCTAssertEqual(listing.entries.first { $0.name == "link" }?.isDir, false)
    }

    func testTheDiskCallsAMissingPathOrAFileNotFound() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("LocationListerTests-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let file = root.appendingPathComponent("single.txt")
        try "hi".write(to: file, atomically: true, encoding: .utf8)

        let missing = await LocationLister.list(root.appendingPathComponent("gone").path)
        XCTAssertFalse(missing.exists)
        let aFile = await LocationLister.list(file.path)
        XCTAssertFalse(aFile.exists)
    }
}
