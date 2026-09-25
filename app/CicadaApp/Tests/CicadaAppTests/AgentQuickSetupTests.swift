import XCTest
@testable import CicadaApp

/// Round-4 D5 (C5, R-FA15) — copy one prompt, open Cursor, or merge Claude desktop's config — never replacing it.
final class AgentQuickSetupTests: XCTestCase {
    private let server = ClaudeDesktopConfig.server(python: "/x/cicada/api/.venv/bin/python",
                                                    script: "/x/cicada/mcp/server.py", memory: "/x/cicada/memory")

    private func object(_ data: Data) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testNoFileBecomesAFileWithOnlyCicada() throws {
        guard case .write(let data) = ClaudeDesktopConfig.merge(existing: nil, server: server) else { return XCTFail() }
        let servers = try XCTUnwrap(try object(data)["mcpServers"] as? [String: Any])
        XCTAssertEqual(Array(servers.keys), ["cicada"])
    }

    func testAMergeKeepsEveryOtherServerAndSetting() throws {
        let existing = Data(#"{"globalShortcut":"Cmd+Space","mcpServers":{"alpha-project":{"command":"/bin/echo"}}}"#.utf8)
        guard case .write(let data) = ClaudeDesktopConfig.merge(existing: existing, server: server) else { return XCTFail() }
        let root = try object(data)
        XCTAssertEqual(root["globalShortcut"] as? String, "Cmd+Space")
        let servers = try XCTUnwrap(root["mcpServers"] as? [String: Any])
        XCTAssertNotNil(servers["alpha-project"])
        XCTAssertEqual((servers["cicada"] as? [String: Any])?["command"] as? String, "/x/cicada/api/.venv/bin/python")
    }

    func testAnOlderCicadaEntryIsReplacedAndAnIdenticalOneIsLeftAlone() throws {
        let older = Data(#"{"mcpServers":{"cicada":{"command":"/old/python","args":["/old/server.py"]}}}"#.utf8)
        guard case .write = ClaudeDesktopConfig.merge(existing: older, server: server) else { return XCTFail() }
        guard case .write(let written) = ClaudeDesktopConfig.merge(existing: nil, server: server) else { return XCTFail() }
        XCTAssertEqual(ClaudeDesktopConfig.merge(existing: written, server: server), .unchanged)
    }

    func testAFileCicadaCannotReadIsLeftUntouched() {
        XCTAssertEqual(ClaudeDesktopConfig.merge(existing: Data("{ not json".utf8), server: server), .unparseable(.notJSON))
        XCTAssertEqual(ClaudeDesktopConfig.merge(existing: Data("[1,2]".utf8), server: server), .unparseable(.notAnObject))
        XCTAssertEqual(ClaudeDesktopConfig.merge(existing: Data(#"{"mcpServers":"x"}"#.utf8), server: server),
                       .unparseable(.serversNotAnObject))
        guard case .write = ClaudeDesktopConfig.merge(existing: Data("  \n".utf8), server: server) else {
            return XCTFail("an empty file is an empty config")
        }
    }

    func testApplyBacksUpFirstAndNeverCreatesClaudesFolder() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("claude-\(UUID())")
        defer { try? FileManager.default.removeItem(at: home) }
        let url = ClaudeDesktopConfig.configURL(home: home)
        XCTAssertEqual(ClaudeDesktopConfig.apply(server: server, at: url), .claudeNotSetUp)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.deletingLastPathComponent().path))
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let original = Data(#"{"mcpServers":{"alpha-project":{"command":"/bin/echo"}}}"#.utf8)
        try original.write(to: url)
        XCTAssertEqual(ClaudeDesktopConfig.apply(server: server, at: url), .done)
        XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: url.path + ClaudeDesktopConfig.backupSuffix)), original)
        XCTAssertEqual(ClaudeDesktopConfig.apply(server: server, at: url), .alreadySetUp)
        XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: url.path + ClaudeDesktopConfig.backupSuffix)), original,
                       "a no-op never overwrites the backup of the person's own file")
        try Data("{ broken".utf8).write(to: url)
        XCTAssertEqual(ClaudeDesktopConfig.apply(server: server, at: url), .leftUntouched(.notJSON))
        XCTAssertEqual(try Data(contentsOf: url), Data("{ broken".utf8))
    }

    /// R-FA15 — a config kept as a symlink (a dotfiles repo) is written through the link, never replaced by a file.
    func testASymlinkedConfigStaysALink() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("claude-\(UUID())")
        defer { try? FileManager.default.removeItem(at: home) }
        let url = ClaudeDesktopConfig.configURL(home: home)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let real = home.appendingPathComponent("dotfiles/claude_desktop_config.json")
        try FileManager.default.createDirectory(at: real.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(#"{"mcpServers":{}}"#.utf8).write(to: real)
        try FileManager.default.createSymbolicLink(at: url, withDestinationURL: real)
        XCTAssertEqual(ClaudeDesktopConfig.apply(server: server, at: url), .done)
        XCTAssertNotNil(try? FileManager.default.destinationOfSymbolicLink(atPath: url.path), "still a link")
        let servers = try XCTUnwrap(try object(Data(contentsOf: real))["mcpServers"] as? [String: Any])
        XCTAssertNotNil(servers["cicada"], "the person's own file got the entry")
    }

    func testTheSetupWireDecodesLeniently() throws {
        let prompt = try JSONDecoder().decode(AgentSetupPrompt.self, from: Data(#"""
            {"harness":"codex","kind":"prompt","title":"Codex","prompt":"Please run …","argv":[["codex","mcp","add","cicada"]],
             "display":["codex mcp add cicada"]}
            """#.utf8))
        XCTAssertEqual(prompt.kind, "prompt")
        XCTAssertEqual(prompt.display, ["codex mcp add cicada"])
        let bare = try JSONDecoder().decode(AgentSetupPrompt.self, from: Data(#"{"harness":"cursor"}"#.utf8))
        XCTAssertNil(bare.prompt)
        XCTAssertEqual(bare.argv, [])
    }

    func testEachHarnessGetsItsOwnActions() throws {
        let prompt = try JSONDecoder().decode(AgentSetupPrompt.self, from: Data(#"{"harness":"claude-code","kind":"prompt","prompt":"Hi"}"#.utf8))
        let step = AgentWiringStep(step: "mcp", display: "claude mcp add cicada …", argv: ["/bin/claude"], touches: [])
        let wired = AgentWiring(id: "claude-code", installed: true, binary: "/bin/claude", recall: "off", autosave: "off",
                                connect: [step], detail: nil)
        XCTAssertEqual(AgentQuickSetup.actions(catalogId: "claude-code", setup: prompt, wiring: wired),
                       [.connectForMe([step]), .copyPrompt("Hi")])
        XCTAssertEqual(AgentQuickSetup.actions(catalogId: "claude-code", setup: nil, wiring: nil), [],
                       "today's backend: no prompt, no wiring — nothing new to show")
        XCTAssertEqual(AgentQuickSetup.actions(catalogId: "cursor", setup: nil, wiring: nil), [.openCursor])
        XCTAssertEqual(AgentQuickSetup.actions(catalogId: "claude-desktop", setup: nil, wiring: nil), [.setUpClaude])
        XCTAssertEqual(AgentQuickSetup.actions(catalogId: "hermes", setup: prompt, wiring: nil), [.copyPrompt("Hi")])
        XCTAssertEqual(AgentCatalog.setupHarnesses,
                       ["claude-code", "codex", "gemini-cli", "cursor", "claude-desktop", "opencode", "hermes", "openclaw",
                        "claude", "chatgpt", "grok"])
    }
}
