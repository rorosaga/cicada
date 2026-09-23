import XCTest
@testable import CicadaApp

/// Track Z R-Z10 / design §7.4 (Z-B5) — the door every intake passes. Built on
/// a temporary home: no test here reads, lists or resolves the person's own
/// `~/.claude`, `~/.codex` or `~/.cicada`.
final class FeedGuardTests: XCTestCase {
    private var home: URL!

    override func setUpWithError() throws {
        home = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("feedguard-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: home) }

    @discardableResult
    private func file(_ path: String, _ body: String = "{}") throws -> URL {
        let url = home.appendingPathComponent(path)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(body.utf8).write(to: url)
        return url
    }

    private func link(_ path: String, to target: URL) throws -> URL {
        let url = home.appendingPathComponent(path)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(at: url, withDestinationURL: target)
        return url
    }

    private func verdict(_ urls: [URL], env: [String: String] = [:]) -> IntakeAdmission {
        IntakeRouter.feedGuard(urls: urls, home: home, env: env)
    }

    private func refusal(_ urls: [URL], env: [String: String] = [:]) -> FeedRefusal? {
        if case .refused(let why) = verdict(urls, env: env) { return why }
        return nil
    }

    func test_aChatGPTExportInDownloadsIsAdmitted() throws {
        let export = try file("Downloads/conversations.json")
        XCTAssertEqual(verdict([export]), .admitted(files: [export], capped: false))
    }

    func test_eachRefusedRootIsRefused_theFolderBeforeItIsWalked() throws {
        let transcript = try file(".claude/projects/alpha-project/session.json")
        XCTAssertEqual(refusal([transcript]), .claudeSessions)
        XCTAssertEqual(refusal([home.appendingPathComponent(".claude")]), .claudeSessions)
        XCTAssertEqual(refusal([try file(".codex/sessions/rollout.json")]), .codexSessions)
        XCTAssertEqual(refusal([try file(".cicada/remote/settings.json")]), .cicadaHome)
        let export = try file("Downloads/conversations.json")
        XCTAssertEqual(refusal([export, transcript]), .claudeSessions, "one refused URL refuses the drop")
    }

    func test_theEnvironmentsOwnHomesAreRefusedToo() throws {
        let claude = try file("elsewhere/claude-config/x.json")
        XCTAssertEqual(refusal([claude], env: ["CLAUDE_CONFIG_DIR": claude.deletingLastPathComponent().path]),
                       .claudeSessions)
        let codex = try file("elsewhere/codex-home/x.json")
        XCTAssertEqual(refusal([codex], env: ["CODEX_HOME": codex.deletingLastPathComponent().path]), .codexSessions)
        let cicada = try file("elsewhere/cicada-home/x.json")
        XCTAssertEqual(refusal([cicada], env: ["CICADA_HOME": cicada.deletingLastPathComponent().path]), .cicadaHome)
        XCTAssertNil(refusal([claude], env: ["CLAUDE_CONFIG_DIR": ""]), "an empty variable names no root")
    }

    func test_aSymlinkIsJudgedByWhereItPoints() throws {
        let transcripts = try file(".claude/projects/alpha-project/a.json").deletingLastPathComponent()
        XCTAssertEqual(refusal([try link("Downloads/looks-harmless", to: transcripts)]), .claudeSessions)
        try file("Downloads/export/conversations.json")
        _ = try link("Downloads/export/extra.json", to: try file(".cicada/secrets.json"))
        XCTAssertEqual(refusal([home.appendingPathComponent("Downloads/export")]), .cicadaHome,
                       "a link inside an innocent folder")
    }

    /// Z-B5 — "refused before it is walked", observed through the walk seam: a
    /// dropped session folder is never handed to the walk, and a refused root
    /// met INSIDE a dropped folder (a visible `$CLAUDE_CONFIG_DIR`) is pruned —
    /// nothing under it is listed — and refuses the drop.
    func test_aRefusedRootIsNeverWalked() throws {
        var walked: [[String]] = []
        var pruned: [String] = []
        func guardWalking(_ urls: [URL], env: [String: String] = [:]) -> IntakeAdmission {
            IntakeRouter.feedGuard(urls: urls, home: home, env: env) { urls, prune in
                walked.append(urls.map(\.lastPathComponent))
                return IntakeRouter.expand(urls) { url in
                    let skip = prune(url)
                    if skip { pruned.append(url.lastPathComponent) }
                    return skip
                }
            }
        }
        let transcripts = try file(".claude/projects/alpha-project/a.json").deletingLastPathComponent()
        XCTAssertEqual(guardWalking([transcripts]), .refused(.claudeSessions))
        XCTAssertEqual(walked, [], "a dropped session folder is refused before any walk")
        try file("Documents/claude-config/projects/alpha-project/b.json")
        try file("Documents/notes.json")
        let config = home.appendingPathComponent("Documents/claude-config")
        XCTAssertEqual(guardWalking([home.appendingPathComponent("Documents")], env: ["CLAUDE_CONFIG_DIR": config.path]),
                       .refused(.claudeSessions))
        XCTAssertEqual(walked, [["Documents"]])
        XCTAssertEqual(pruned, ["claude-config"], "the root itself is pruned; nothing under it is listed")
    }

    func test_aSiblingNameIsNotTheRoot() throws {
        let near = try file(".claudette/notes.json")
        XCTAssertEqual(verdict([near]), .admitted(files: [near], capped: false))
    }

    func test_nothingExportShapedIsUnreadable() throws {
        XCTAssertEqual(refusal([try file("Downloads/cat.png", "png")]), .unreadable)
        try file("Downloads/photos/a.png", "png")
        XCTAssertEqual(refusal([home.appendingPathComponent("Downloads/photos")]), .unreadable)
    }

    func test_everyRefusalHasPanelWords() {
        for why in FeedRefusal.allCases { XCTAssertFalse(why.panelText.isEmpty, "\(why)") }
        XCTAssertEqual(FeedRefusal.unreadable.panelText, Copy.intakeNothingReadable, "the old empty-drop words")
    }
}
