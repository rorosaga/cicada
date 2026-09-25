import XCTest
@testable import CicadaApp

/// Track I T7 (design §4.1.6) — the copy-paste snippets Settings → Agents shows
/// and the argv the app runs are the SAME commands. `api/tests/test_agent_wiring.py`
/// reads the same fixture, so a change on either side goes red here or there.
final class AgentWiringCatalogTests: XCTestCase {
    private struct Fixture: Decodable {
        struct Case: Decodable { let agent: String; let step: String; let argv: [String] }
        let root: String
        let memory: String
        let cases: [Case]
    }

    /// POSIX-ish splitting for the two snippets: single quotes (with the `'\''`
    /// idiom `SnippetEscape.shell` emits), double quotes with backslash escapes,
    /// and spaces.
    private func shellWords(_ s: String) -> [String] {
        var words: [String] = [], word = "", inWord = false, quote: Character? = nil, escape = false
        for c in s {
            if escape { word.append(c); escape = false; continue }
            if let q = quote {
                if c == q { quote = nil } else if c == "\\" && q == "\"" { escape = true } else { word.append(c) }
                continue
            }
            switch c {
            case "'", "\"": quote = c; inWord = true
            case "\\": escape = true; inWord = true
            case " ", "\n": if inWord { words.append(word); word = ""; inWord = false }
            default: word.append(c); inWord = true
            }
        }
        if inWord { words.append(word) }
        return words
    }

    func testTheSnippetsRunExactlyWhatTheAppWouldRun() throws {
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: repo.appendingPathComponent("api/tests/fixtures/agent_wiring_argv.json"))
        let fixture = try JSONDecoder().decode(Fixture.self, from: data)
        XCTAssertEqual(fixture.cases.count, 2, "a table test over nothing passes vacuously")
        let catalog = AgentSetupCatalog.all(home: fixture.root, memoryRoot: fixture.memory)
        for c in fixture.cases {
            let setup = try XCTUnwrap(catalog.first { $0.id == c.agent }, c.agent)
            let command = try XCTUnwrap(setup.steps.first?.command, c.agent)
            XCTAssertEqual(shellWords(command), c.argv, c.agent)
        }
    }

    /// Decode tolerance (plan Global Constraints): the backend model defaults
    /// every field but `id`/`step`/`argv`, so a payload without them decodes,
    /// and a missing `recall` is `unknown` — never the `off` that offers an add.
    func testTheWireModelDecodesAPayloadThatOmitsDefaultedFields() throws {
        let json = #"{"agents":[{"id":"codex","connect":[{"step":"mcp","argv":["codex","mcp"]}]}]}"#
        let decoded = try JSONDecoder().decode(AgentWiringResponse.self, from: Data(json.utf8))
        let codex = try XCTUnwrap(decoded.agents.first)
        XCTAssertFalse(codex.installed)
        XCTAssertNil(codex.binary)
        XCTAssertEqual(codex.recall, "unknown")
        XCTAssertEqual(codex.autosave, "n/a")
        XCTAssertEqual(codex.connect.first?.display, "codex mcp")
        XCTAssertEqual(codex.connect.first?.touches, [])
        XCTAssertEqual(decoded.python, "")
    }
}
