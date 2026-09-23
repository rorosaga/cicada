import XCTest
@testable import CicadaApp

/// G133 — the walk, the change decision, and the batches (R-F1, R-LS8).
final class FolderScannerTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("FolderScannerTests-\(UUID().uuidString)")
        for (rel, text) in ["README.md": "# alpha-project", "research/plan.md": "plan",
                            "web/node_modules/pkg/readme.md": "vendored", ".git/HEAD": "ref", "notes.txt": "x"] {
            let url = root.appendingPathComponent(rel)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try text.write(to: url, atomically: true, encoding: .utf8)
        }
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent("outside.md"),
                                                   withDestinationURL: URL(fileURLWithPath: "/etc/hosts"))
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: root) }

    private var rules: CompiledFolderRules {
        CompiledFolderRules(include: ["**/*.md"], exclude: ["**/.git/**", "**/node_modules/**"], authorship: [])
    }

    func testTheWalkKeepsIncludedFilesAndNeverFollowsASymlink() {
        XCTAssertEqual(Set(FolderScanner.walk(root: root, rules: rules).files.keys), ["README.md", "research/plan.md"])
    }

    func testOnlyAMovedStatIsReadAndOnlyChangedBytesAreUploaded() throws {
        let current = FolderScanner.walk(root: root, rules: rules).files
        let first = FolderScanner.candidates(current: current, manifest: [:])
        XCTAssertEqual(first.changed, ["README.md", "research/plan.md"])
        let read = FolderScanner.readUploads(root: root, changed: first.changed, current: current, manifest: [:])
        XCTAssertEqual(read.uploads.map(\.relpath), ["README.md", "research/plan.md"])
        var manifest: [String: FolderFileSignature] = [:]
        for u in read.uploads { manifest[u.relpath] = FolderFileSignature(size: u.size, modified: u.mtime, sha256: u.sha256) }
        XCTAssertEqual(FolderScanner.candidates(current: current, manifest: manifest).changed, [])

        // Same bytes, new mtime: read and hashed, never uploaded.
        try FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSinceNow: 60)],
                                              ofItemAtPath: root.appendingPathComponent("README.md").path)
        let touched = FolderScanner.walk(root: root, rules: rules).files
        let again = FolderScanner.candidates(current: touched, manifest: manifest)
        XCTAssertEqual(again.changed, ["README.md"])
        let reread = FolderScanner.readUploads(root: root, changed: again.changed, current: touched, manifest: manifest)
        XCTAssertTrue(reread.uploads.isEmpty)
        XCTAssertEqual(Array(reread.touched.keys), ["README.md"])

        try FileManager.default.removeItem(at: root.appendingPathComponent("research/plan.md"))
        XCTAssertEqual(FolderScanner.candidates(current: FolderScanner.walk(root: root, rules: rules).files,
                                                manifest: manifest).deleted, ["research/plan.md"])
    }

    /// Review r1: a folder the app cannot list is not an empty folder. The walk
    /// says so, and nothing under what it could not see is called deleted.
    func testAnUnlistableFolderIsNeverReadAsEmpty() throws {
        let manifest = ["README.md": FolderFileSignature(size: 1, modified: 1, sha256: "x"),
                        "research/plan.md": FolderFileSignature(size: 1, modified: 1, sha256: "y")]

        let research = root.appendingPathComponent("research")
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: research.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: research.path) }
        let partial = FolderScanner.walk(root: root, rules: rules)
        XCTAssertNil(partial.rootError, "only a subfolder was refused")
        XCTAssertEqual(partial.unlisted, ["research"])
        let plan = FolderScanner.candidates(current: partial.files, manifest: manifest, unlisted: partial.unlisted)
        XCTAssertEqual(plan.deleted, [], "a file the walk could not look for is not gone")
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: research.path)

        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: root.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: root.path) }
        let refused = FolderScanner.walk(root: root, rules: rules)
        XCTAssertEqual(refused.rootError, .permissionDenied)
        XCTAssertTrue(refused.files.isEmpty)
        XCTAssertEqual(FolderScanner.candidates(current: refused.files, manifest: manifest,
                                                unlisted: refused.unlisted).deleted, [])
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: root.path)

        let gone = FolderScanner.walk(root: root.appendingPathComponent("not-here"), rules: rules)
        XCTAssertEqual(gone.rootError, .unreachable)
    }

    func testSha256AndBatches() {
        XCTAssertEqual(FolderScanner.sha256(Data("abc".utf8)),
                       "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        let big = FolderUpload(relpath: "a", size: 4_000_000, mtime: 0, sha256: "", data: Data(count: 4_000_000))
        let small = FolderUpload(relpath: "b", size: 1, mtime: 0, sha256: "", data: Data(count: 1))
        XCTAssertEqual(FolderScanner.batches([big, big, small]).map { $0.map(\.relpath) }, [["a"], ["a", "b"]])
        let many = (0..<(FolderScanner.maxBatchFiles + 1)).map {
            FolderUpload(relpath: "\($0)", size: 1, mtime: 0, sha256: "", data: Data(count: 1))
        }
        XCTAssertEqual(FolderScanner.batches(many).map(\.count), [FolderScanner.maxBatchFiles, 1])
    }
}
