import XCTest
@testable import CicadaApp

/// G133 — the app's glob matcher runs the SAME table as
/// `api/tests/test_folder_source.py::GLOB_TABLE`. Change one, change both.
final class FolderGlobTests: XCTestCase {
    static let table: [(String, String, Bool)] = [
        ("**/*.md", "README.md", true),
        ("**/*.md", "research/plan.md", true),
        ("**/*.md", "notes.txt", false),
        ("*.md", "research/plan.md", false),
        ("archive/**", "archive/2026-01/sweep.md", true),
        ("archive/**", "research/archive/x.md", false),
        ("**/.git/**", ".git/HEAD", true),
        ("**/.git/**", "sub/.git/config", true),
        ("**/node_modules/**", "web/node_modules/a/b.md", true),
        ("docs/?.md", "docs/a.md", true),
        ("docs/?.md", "docs/ab.md", false),
    ]

    func testTheSharedTable() {
        for (pattern, relpath, expected) in Self.table {
            XCTAssertEqual(FolderGlob.matches(pattern, relpath), expected, "\(pattern) vs \(relpath)")
        }
    }

    func testCompiledRulesIncludeExcludeAndAuthorship() {
        let rules = CompiledFolderRules(include: ["**/*.md"], exclude: ["**/node_modules/**"],
                                        authorship: [FolderAuthorshipRule(glob: "archive/**", authorship: "agent")])
        XCTAssertTrue(rules.included("README.md"))
        XCTAssertFalse(rules.included("web/node_modules/x.md"))
        XCTAssertTrue(rules.excludesDirectory("web/node_modules"))
        XCTAssertFalse(rules.excludesDirectory("research"))
        XCTAssertEqual(rules.authorship("archive/2026/sweep.md"), "agent")
        XCTAssertEqual(rules.authorship("README.md"), "user")
    }

    func testRegistrationsDecodeFromAnOlderOrNewerBackend() throws {
        let json = #"{"id": "alpha-project-1a2b3c", "label": "alpha-project", "somethingNew": 1}"#
        let folder = try JSONDecoder().decode(FolderRegistration.self, from: Data(json.utf8))
        XCTAssertEqual(folder.channelId, "folder:alpha-project-1a2b3c")
        XCTAssertEqual(folder.include, [])
        XCTAssertFalse(folder.papersPending)
        let empty = try JSONDecoder().decode(FolderSyncResult.self, from: Data("{}".utf8))
        XCTAssertEqual(empty, FolderSyncResult())
        let settings = try JSONDecoder().decode(WisprFlowSettings.self, from: Data("{}".utf8))
        XCTAssertEqual(settings, WisprFlowSettings())
    }
}
