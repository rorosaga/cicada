import XCTest
@testable import CicadaApp

/// G88 follow-up — a Devin-flagged split-brain: `AgentSetupCatalog.all()`
/// used to derive `CICADA_MEMORY_PATH` purely from the local
/// `installRoot()` guess (`<home>/memory`), which can disagree with
/// whatever root the app's own already-running backend was actually
/// configured with (e.g. a default `install.sh` run outside `~/cicada`
/// bakes the launchd backend to `~/cicada/memory` regardless of checkout
/// location). A copy-pasted command then registers an agent against a
/// different bank than the app itself talks to — the same bug class as the
/// MCP bank-resolution split-brain fixed 2026-07-03, just on the app side.
///
/// The fix: `all(memoryRoot:)` accepts the LIVE root read from
/// `GET /healthz` (`ConnectView.refreshLiveMemoryRoot()`) and, when
/// present, it wins over the local guess everywhere `CICADA_MEMORY_PATH`
/// is emitted — not just the one call site Devin pointed at. These tests
/// pin every surface that contract touches.
final class AgentSetupCatalogMemoryRootTests: XCTestCase {

    private func steps(_ agents: [AgentSetup], id: String) -> [String] {
        agents.first { $0.id == id }?.steps.compactMap(\.command) ?? []
    }

    // MARK: - No live root yet: falls back to the local <home>/memory guess

    func testNoMemoryRootFallsBackToHomeSlashMemory() {
        let agents = AgentSetupCatalog.all(home: "/x/repo")
        let claudeCode = steps(agents, id: "claude-code")
        XCTAssertTrue(claudeCode.contains { $0.contains("CICADA_MEMORY_PATH=/x/repo/memory") })
    }

    func testEmptyStringMemoryRootIsTreatedAsAbsent() {
        // Mirrors installRoot()'s "empty stamp == absent" contract instead of
        // silently emitting `CICADA_MEMORY_PATH=` with nothing after it.
        let agents = AgentSetupCatalog.all(home: "/x/repo", memoryRoot: "")
        let claudeCode = steps(agents, id: "claude-code")
        XCTAssertTrue(claudeCode.contains { $0.contains("CICADA_MEMORY_PATH=/x/repo/memory") })
    }

    // MARK: - A live root wins, everywhere CICADA_MEMORY_PATH appears

    func testLiveMemoryRootOverridesTheLocalGuessForClaudeCode() {
        let agents = AgentSetupCatalog.all(home: "/x/repo", memoryRoot: "/x/actual-root/memory")
        let claudeCode = steps(agents, id: "claude-code")
        XCTAssertTrue(claudeCode.contains { $0.contains("CICADA_MEMORY_PATH=/x/actual-root/memory") })
        XCTAssertFalse(claudeCode.contains { $0.contains("/x/repo/memory") })
    }

    func testLiveMemoryRootAlsoOverridesTheSharedMCPJSONBlock() {
        // Cursor and Claude Desktop both embed the same `mcpJSON` literal —
        // a single shared computation this bug class could easily miss.
        let agents = AgentSetupCatalog.all(home: "/x/repo", memoryRoot: "/x/actual-root/memory")
        for id in ["cursor", "claude-desktop"] {
            let cmds = steps(agents, id: id)
            XCTAssertTrue(
                cmds.contains { $0.contains(#""CICADA_MEMORY_PATH": "/x/actual-root/memory""#) },
                "\(id) should embed the live root in its mcpJSON block"
            )
            XCTAssertFalse(
                cmds.contains { $0.contains("/x/repo/memory") },
                "\(id) should not still show the local guess once a live root is known"
            )
        }
    }

    func testLiveMemoryRootFlowsIntoTheCursorDeeplink() {
        let withoutOverride = AgentSetupCatalog.all(home: "/x/repo")
        let withOverride = AgentSetupCatalog.all(home: "/x/repo", memoryRoot: "/x/actual-root/memory")
        let cursorURLWithout = withoutOverride.first { $0.id == "cursor" }?.deeplink?.url.absoluteString
        let cursorURLWith = withOverride.first { $0.id == "cursor" }?.deeplink?.url.absoluteString
        XCTAssertNotNil(cursorURLWithout)
        XCTAssertNotNil(cursorURLWith)
        XCTAssertNotEqual(cursorURLWithout, cursorURLWith, "the base64 deeplink payload must change when the root changes")
    }

    // MARK: - `home` (python/server executable paths) is independent of memoryRoot

    func testHomeStillDrivesThePythonAndServerPathsRegardlessOfMemoryRoot() {
        let agents = AgentSetupCatalog.all(home: "/x/repo", memoryRoot: "/x/actual-root/memory")
        let claudeCode = steps(agents, id: "claude-code")
        XCTAssertTrue(claudeCode.contains { $0.contains("/x/repo/api/.venv/bin/python") })
        XCTAssertTrue(claudeCode.contains { $0.contains("/x/repo/mcp/server.py") })
    }
}
