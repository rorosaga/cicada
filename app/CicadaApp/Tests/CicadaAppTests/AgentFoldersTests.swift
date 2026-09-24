import XCTest
@testable import CicadaApp

/// R-HS17 — "Written by an agent" in plain words. The wire stays a glob; the rule between a
/// checkbox and a glob is held to `FolderGlob`, the backend matcher's twin (G133).
final class AgentFoldersTests: XCTestCase {
    func testAFolderIsTheWholeSubtreeBelowIt() {
        let glob = AgentFolders.glob(forSubfolder: "research")
        XCTAssertEqual(glob, "research/**")
        XCTAssertTrue(FolderGlob.matches(glob, "research/plan.md"))
        XCTAssertTrue(FolderGlob.matches(glob, "research/2026/sweep.md"))
        XCTAssertFalse(FolderGlob.matches(glob, "researcher/plan.md"))
        XCTAssertFalse(FolderGlob.matches(glob, "notes/research/plan.md"))
        XCTAssertEqual(AgentFolders.glob(forSubfolder: "/research/deep/"), "research/deep/**", "trimmed of slashes")
    }

    func testOnlyAOneFolderRuleReadsBackAsAFolder() {
        XCTAssertEqual(AgentFolders.subfolder(fromGlob: "research/**"), "research")
        XCTAssertEqual(AgentFolders.subfolder(fromGlob: "research/deep/**"), "research/deep")
        for rule in ["**/*.md", "*.draft.md", "research/*", "docs/?.md", "/**", "**"] {
            XCTAssertNil(AgentFolders.subfolder(fromGlob: rule), rule)
        }
    }

    /// A new folder: one row per subfolder, "archive" ticked only when it exists — the old default
    /// glob's effect, exactly (it matched nothing without an archive folder).
    func testANewFolderPreTicksArchiveOnlyWhenItExists() {
        let rows = AgentFolders.initialRows(subfolders: ["archive", "drafts", "research"])
        XCTAssertEqual(rows.map(\.title), ["Files in archive (and its subfolders)", "Files in drafts (and its subfolders)",
                                           "Files in research (and its subfolders)"])
        XCTAssertEqual(AgentFolders.globs(rows), ["archive/**"])
        XCTAssertEqual(AgentFolders.globs(AgentFolders.initialRows(subfolders: ["drafts"])), [])
        XCTAssertTrue(rows.allSatisfy { !$0.title.contains("**") }, "no glob jargon on screen")
    }

    /// Manage: every saved rule survives a round trip — a folder that moved or sits deeper keeps
    /// its row, and a rule that is not one folder stays verbatim.
    func testASavedRuleIsNeverDropped() {
        let globs = ["research/**", "deep/inside/**", "*.draft.md"]
        let rows = AgentFolders.rows(subfolders: ["drafts", "research"], globs: globs)
        XCTAssertEqual(rows.map(\.title), ["Files in drafts (and its subfolders)", "Files in research (and its subfolders)",
                                           "Files in deep/inside (and its subfolders)", "Files matching *.draft.md"])
        XCTAssertEqual(rows.map(\.isOn), [false, true, true, true])
        XCTAssertEqual(Set(AgentFolders.globs(rows)), Set(globs))
    }

    func testAPickedSubfolderIsTickedOrAdded() {
        let rows = AgentFolders.initialRows(subfolders: ["drafts"])
        XCTAssertEqual(AgentFolders.globs(AgentFolders.adding("drafts", to: rows)), ["drafts/**"])
        let added = AgentFolders.adding("drafts/agent-sweeps", to: rows)
        XCTAssertEqual(added.count, 2)
        XCTAssertEqual(AgentFolders.globs(added), ["drafts/agent-sweeps/**"])
    }

    func testAPickMustBeInsideTheFolder() {
        let root = URL(fileURLWithPath: "/tmp/example-notes")
        XCTAssertEqual(AgentFolders.relativePath(of: root.appendingPathComponent("research/deep"), under: root),
                       "research/deep")
        XCTAssertNil(AgentFolders.relativePath(of: root, under: root), "the folder itself is not a subfolder")
        XCTAssertNil(AgentFolders.relativePath(of: URL(fileURLWithPath: "/tmp/elsewhere"), under: root))
        XCTAssertNil(AgentFolders.relativePath(of: URL(fileURLWithPath: "/tmp/example-notes-2/x"), under: root))
    }

    /// The app reads the folder (G133): directories only, hidden ones skipped, in Finder's order.
    func testTheFolderIsListedByTheApp() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        for dir in ["research", "Archive", ".git", "drafts"] {
            try FileManager.default.createDirectory(at: root.appendingPathComponent(dir), withIntermediateDirectories: true)
        }
        try Data("x".utf8).write(to: root.appendingPathComponent("notes.md"))
        defer { try? FileManager.default.removeItem(at: root) }
        XCTAssertEqual(AgentFolders.subfolders(in: root), ["Archive", "drafts", "research"])
        XCTAssertEqual(AgentFolders.subfolders(in: root.appendingPathComponent("missing")), [])
    }
}
