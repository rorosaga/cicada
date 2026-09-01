import XCTest
@testable import CicadaApp

/// Devin PR #28 round 2 — `AgentSetupCatalog.all(home:memoryRoot:)` used to
/// interpolate raw filesystem paths into shell, JSON, TOML and YAML
/// snippets. A home like `/Users/Jane Doe` (spaces are common on macOS), or
/// one carrying a quote or a backslash, pasted as a broken or silently
/// altered command/config. Every path now goes through `SnippetEscape`'s
/// per-format helper; these tests round-trip the nastiest plausible home
/// through each format, and pin the plain-path output byte-for-byte so the
/// common case is exactly what it was before.
final class AgentSetupCatalogEscapingTests: XCTestCase {

    /// Space, apostrophe, double quotes and a backslash — one of each.
    private let home = #"/Users/Jane Doe/it's "here"\x"#
    private var python: String { "\(home)/api/.venv/bin/python" }
    private var server: String { "\(home)/mcp/server.py" }
    private var memory: String { "\(home)/memory" }

    private func agent(_ id: String, home: String) -> AgentSetup {
        AgentSetupCatalog.all(home: home).first { $0.id == id }!
    }

    private func commands(_ id: String, home: String) -> [String] {
        agent(id, home: home).steps.compactMap(\.command)
    }

    /// What `/bin/sh` actually hands a program for `word` — the only judge
    /// of whether a shell escaping is right.
    private func shellExpands(_ word: String) throws -> String {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        p.arguments = ["-c", "printf '%s' \(word)"]
        let pipe = Pipe()
        p.standardOutput = pipe
        try p.run()
        p.waitUntilExit()
        return String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
    }

    private func mcpServer(fromJSON text: String) throws -> [String: Any] {
        let obj = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any]
        let servers = obj?["mcpServers"] as? [String: Any]
        return try XCTUnwrap(servers?["cicada"] as? [String: Any])
    }

    private func assertServer(_ server: [String: Any], file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(server["command"] as? String, python, file: file, line: line)
        XCTAssertEqual(server["args"] as? [String], [self.server], file: file, line: line)
        XCTAssertEqual((server["env"] as? [String: String])?["CICADA_MEMORY_PATH"], memory, file: file, line: line)
    }

    // MARK: - Helpers, in isolation

    func testShellHelperIsTheIdentityForAPlainPathAndSingleQuotesOtherwise() throws {
        XCTAssertEqual(SnippetEscape.shell("/x/repo/api/.venv/bin/python"), "/x/repo/api/.venv/bin/python")
        XCTAssertEqual(SnippetEscape.shell(home), #"'/Users/Jane Doe/it'\''s "here"\x'"#)
        XCTAssertEqual(try shellExpands(SnippetEscape.shell(home)), home)
        XCTAssertEqual(try shellExpands(SnippetEscape.shell("/x/$HOME/`id`/*")), "/x/$HOME/`id`/*")
    }

    func testShellDoubleQuotedHelperEscapesOnlyWhatDoubleQuotesInterpret() throws {
        XCTAssertEqual(SnippetEscape.shellDoubleQuoted("/x/repo/mcp/server.py"), "/x/repo/mcp/server.py")
        XCTAssertEqual(SnippetEscape.shellDoubleQuoted(home), #"/Users/Jane Doe/it's \"here\"\\x"#)
        XCTAssertEqual(try shellExpands("\"\(SnippetEscape.shellDoubleQuoted(home))\""), home)
        XCTAssertEqual(try shellExpands("\"\(SnippetEscape.shellDoubleQuoted("/x/$HOME/`id`"))\""), "/x/$HOME/`id`")
    }

    func testJSONTOMLAndYAMLHelpersEscapeBackslashQuoteAndControlCharacters() {
        let raw = "a\\b\"c\td\ne\u{01}"
        let escaped = #"a\\b\"c\td\ne\u0001"#
        XCTAssertEqual(SnippetEscape.json(raw), escaped)
        XCTAssertEqual(SnippetEscape.toml(raw), escaped)
        XCTAssertEqual(SnippetEscape.yaml(raw), escaped)
        XCTAssertEqual(SnippetEscape.json("/x/repo/memory"), "/x/repo/memory")
        XCTAssertEqual(
            try JSONSerialization.jsonObject(with: Data("[\"\(SnippetEscape.json(raw))\"]".utf8)) as? [String],
            [raw]
        )
    }

    // MARK: - JSON snippets parse and yield the exact paths

    func testMCPJSONBlockParsesAndYieldsTheExactPaths() throws {
        for id in ["cursor", "claude-desktop"] {
            let json = try XCTUnwrap(commands(id, home: home).first, id)
            assertServer(try mcpServer(fromJSON: json))
        }
    }

    func testCursorDeeplinkPayloadRoundTripsThroughBase64() throws {
        let url = try XCTUnwrap(agent("cursor", home: home).deeplink?.url)
        let query = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems)
        let b64 = try XCTUnwrap(query.first { $0.name == "config" }?.value?.removingPercentEncoding)
        let data = try XCTUnwrap(Data(base64Encoded: b64))
        let server = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        assertServer(server)
    }

    // MARK: - Shell snippets: the single-quoted form, and what sh makes of it

    func testClaudeCodeCommandsSingleQuoteEveryPath() throws {
        let cmds = commands("claude-code", home: home)
        XCTAssertEqual(cmds.count, 2)
        let quotedPython = #"'/Users/Jane Doe/it'\''s "here"\x/api/.venv/bin/python'"#
        let quotedServer = #"'/Users/Jane Doe/it'\''s "here"\x/mcp/server.py'"#
        let quotedMemory = #"'/Users/Jane Doe/it'\''s "here"\x/memory'"#
        XCTAssertEqual(
            cmds[0],
            "claude mcp add cicada --scope user --env CICADA_MEMORY_PATH=\(quotedMemory) -- \(quotedPython) \(quotedServer)"
        )
        XCTAssertEqual(
            cmds[1],
            #"mkdir -p ~/.claude/skills/cicada && cp '/Users/Jane Doe/it'\''s "here"\x/SKILL.md' ~/.claude/skills/cicada/SKILL.md"#
        )
        // The env assignment concatenates a bare prefix with a quoted word;
        // sh must still produce one argument holding the exact path.
        XCTAssertEqual(try shellExpands("CICADA_MEMORY_PATH=\(quotedMemory)"), "CICADA_MEMORY_PATH=\(memory)")
        XCTAssertEqual(try shellExpands(quotedPython), python)
    }

    func testDoubleQuotedCLICommandsEscapeInsideTheirQuotes() throws {
        let dqPython = #""/Users/Jane Doe/it's \"here\"\\x/api/.venv/bin/python""#
        let dqServer = #""/Users/Jane Doe/it's \"here\"\\x/mcp/server.py""#
        let dqMemory = #""/Users/Jane Doe/it's \"here\"\\x/memory""#
        XCTAssertEqual(
            commands("openclaw", home: home),
            ["openclaw mcp add cicada --command \(dqPython) --arg \(dqServer) --env CICADA_MEMORY_PATH=\(dqMemory)"]
        )
        XCTAssertEqual(
            commands("codex", home: home).first,
            "codex mcp add cicada --env CICADA_MEMORY_PATH=\(dqMemory) -- \(dqPython) \(dqServer)"
        )
        XCTAssertEqual(
            commands("gemini-cli", home: home),
            ["gemini mcp add -s user -e CICADA_MEMORY_PATH=\(dqMemory) cicada \(dqPython) \(dqServer)"]
        )
        XCTAssertEqual(try shellExpands(dqPython), python)
        XCTAssertEqual(try shellExpands("CICADA_MEMORY_PATH=\(dqMemory)"), "CICADA_MEMORY_PATH=\(memory)")
    }

    // MARK: - TOML and YAML: the escaped form

    func testCodexTOMLUsesBasicStringEscapes() throws {
        let toml = try XCTUnwrap(commands("codex", home: home).last)
        XCTAssertEqual(toml, #"""
        [mcp_servers.cicada]
        command = "/Users/Jane Doe/it's \"here\"\\x/api/.venv/bin/python"
        args = ["/Users/Jane Doe/it's \"here\"\\x/mcp/server.py"]
        env = { CICADA_MEMORY_PATH = "/Users/Jane Doe/it's \"here\"\\x/memory" }
        """#)
    }

    func testHermesYAMLUsesDoubleQuotedScalarEscapes() throws {
        let yaml = try XCTUnwrap(commands("hermes", home: home).first)
        XCTAssertEqual(yaml, #"""
        mcp_servers:
          cicada:
            command: "/Users/Jane Doe/it's \"here\"\\x/api/.venv/bin/python"
            args: ["/Users/Jane Doe/it's \"here\"\\x/mcp/server.py"]
            env:
              CICADA_MEMORY_PATH: "/Users/Jane Doe/it's \"here\"\\x/memory"
        """#)
    }

    // MARK: - A plain path is byte-identical to what the page emitted before

    func testPlainPathOutputIsUnchanged() {
        let plain = "/x/repo"
        XCTAssertEqual(commands("claude-code", home: plain), [
            "claude mcp add cicada --scope user --env CICADA_MEMORY_PATH=/x/repo/memory -- /x/repo/api/.venv/bin/python /x/repo/mcp/server.py",
            "mkdir -p ~/.claude/skills/cicada && cp /x/repo/SKILL.md ~/.claude/skills/cicada/SKILL.md",
        ])
        XCTAssertEqual(commands("openclaw", home: plain), [
            #"openclaw mcp add cicada --command "/x/repo/api/.venv/bin/python" --arg "/x/repo/mcp/server.py" --env CICADA_MEMORY_PATH="/x/repo/memory""#,
        ])
        XCTAssertEqual(commands("codex", home: plain), [
            #"codex mcp add cicada --env CICADA_MEMORY_PATH="/x/repo/memory" -- "/x/repo/api/.venv/bin/python" "/x/repo/mcp/server.py""#,
            """
            [mcp_servers.cicada]
            command = "/x/repo/api/.venv/bin/python"
            args = ["/x/repo/mcp/server.py"]
            env = { CICADA_MEMORY_PATH = "/x/repo/memory" }
            """,
        ])
        XCTAssertEqual(commands("gemini-cli", home: plain), [
            #"gemini mcp add -s user -e CICADA_MEMORY_PATH="/x/repo/memory" cicada "/x/repo/api/.venv/bin/python" "/x/repo/mcp/server.py""#,
        ])
        XCTAssertEqual(commands("cursor", home: plain), [
            """
            {
              "mcpServers": {
                "cicada": {
                  "command": "/x/repo/api/.venv/bin/python",
                  "args": ["/x/repo/mcp/server.py"],
                  "env": { "CICADA_MEMORY_PATH": "/x/repo/memory" }
                }
              }
            }
            """,
        ])
        XCTAssertEqual(commands("claude-desktop", home: plain), commands("cursor", home: plain))
        XCTAssertEqual(commands("hermes", home: plain), [
            """
            mcp_servers:
              cicada:
                command: "/x/repo/api/.venv/bin/python"
                args: ["/x/repo/mcp/server.py"]
                env:
                  CICADA_MEMORY_PATH: "/x/repo/memory"
            """,
        ])
        let inner = #"{"command":"/x/repo/api/.venv/bin/python","args":["/x/repo/mcp/server.py"],"env":{"CICADA_MEMORY_PATH":"/x/repo/memory"}}"#
        let b64 = Data(inner.utf8).base64EncodedString().addingPercentEncoding(withAllowedCharacters: .alphanumerics)!
        XCTAssertEqual(
            agent("cursor", home: plain).deeplink?.url.absoluteString,
            "cursor://anysphere.cursor-deeplink/mcp/install?name=cicada&config=\(b64)"
        )
    }
}
