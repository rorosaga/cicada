import XCTest
@testable import CicadaApp

/// G48 §5 — the AppleScript source builders are PURE and REGEX-GATED.
/// Nothing reaches AppleScript that hasn't passed `isSafeCommand`/`isSafeCwd`.
final class TerminalLaunchScriptTests: XCTestCase {

    private let uuid = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"

    // MARK: - Gates

    func testASafeResumeCommandAndCwdPass() {
        XCTAssertTrue(TerminalLauncher.isSafeCommand("claude --resume \(uuid)"))
        XCTAssertTrue(TerminalLauncher.isSafeCwd("/Users/rorosaga/Documents/roros_lab/cicada"))
        XCTAssertTrue(TerminalLauncher.isSafeCwd("~/Documents/roros_lab/cicada"))
    }

    func testQuotesBackslashesAndShellMetacharactersAreRefused() {
        for hostile in [
            #"claude --resume x" & do shell script "rm -rf ~" & ""#,
            #"claude --resume x\"#,
            "claude --resume x; rm -rf ~",
            "claude --resume $(whoami)",
            "claude --resume `id`",
            "claude --resume x\nactivate",
        ] {
            XCTAssertFalse(TerminalLauncher.isSafeCommand(hostile), hostile)
            XCTAssertNil(TerminalLauncher.ghosttyScript(command: hostile, cwd: nil), hostile)
            XCTAssertNil(TerminalLauncher.terminalScript(command: hostile, cwd: nil), hostile)
        }
    }

    func testARelativeOrHostileCwdIsRefused() {
        XCTAssertFalse(TerminalLauncher.isSafeCwd("relative/path"))
        XCTAssertFalse(TerminalLauncher.isSafeCwd("/Users/x/we ird"))
        XCTAssertFalse(TerminalLauncher.isSafeCwd(#"/Users/x/q"uote"#))
    }

    // MARK: - Exact source

    func testGhosttyScriptIsTheVerifiedInvocation() {
        let script = TerminalLauncher.ghosttyScript(
            command: "claude --resume \(uuid)", cwd: "/Users/x/p"
        )
        XCTAssertEqual(script, """
        tell application "Ghostty"
        activate
        new window with configuration {command:"claude --resume \(uuid)", \
        initial working directory:"/Users/x/p"}
        end tell
        """)
    }

    func testGhosttyScriptDropsAnUnsafeCwdButKeepsTheCommand() {
        let script = TerminalLauncher.ghosttyScript(
            command: "claude --resume \(uuid)", cwd: "/Users/x/we ird"
        )
        XCTAssertEqual(script, """
        tell application "Ghostty"
        activate
        new window with configuration {command:"claude --resume \(uuid)"}
        end tell
        """)
    }

    func testTerminalScriptComposesCdAndCommandFromValidatedPiecesOnly() {
        let script = TerminalLauncher.terminalScript(
            command: "claude --resume \(uuid)", cwd: "/Users/x/p"
        )
        XCTAssertEqual(
            script,
            "tell application \"Terminal\"\nactivate\n"
            + "do script \"cd /Users/x/p && claude --resume \(uuid)\"\nend tell"
        )
    }

    // MARK: - Ladder

    func testGhosttyIsPreferredWhenInstalled() {
        var ran: [String] = []
        let outcome = TerminalLauncher.launch(
            command: "claude --resume \(uuid)", cwd: "/Users/x/p",
            ghosttyInstalled: true, run: { ran.append($0); return true }
        )
        XCTAssertEqual(outcome, .ghostty)
        XCTAssertEqual(ran.count, 1)
        XCTAssertTrue(ran[0].contains("Ghostty"))
    }

    func testTerminalIsTheSecondRungWhenGhosttyIsAbsent() {
        var ran: [String] = []
        let outcome = TerminalLauncher.launch(
            command: "claude --resume \(uuid)", cwd: nil,
            ghosttyInstalled: false, run: { ran.append($0); return true }
        )
        XCTAssertEqual(outcome, .terminal)
        XCTAssertEqual(ran.count, 1)
        XCTAssertTrue(ran[0].contains("Terminal"))
    }

    func testTerminalIsTriedWhenGhosttyScriptFails() {
        var ran: [String] = []
        let outcome = TerminalLauncher.launch(
            command: "claude --resume \(uuid)", cwd: nil,
            ghosttyInstalled: true,
            run: { ran.append($0); return !$0.contains("Ghostty") }
        )
        XCTAssertEqual(outcome, .terminal)
        XCTAssertEqual(ran.count, 2)
    }

    func testEverythingFailingFallsBackToTheClipboard() {
        let outcome = TerminalLauncher.launch(
            command: "claude --resume \(uuid)", cwd: nil,
            ghosttyInstalled: true, run: { _ in false }
        )
        XCTAssertEqual(outcome, .clipboard)
    }

    func testAnUnsafeCommandNeverReachesAppleScriptAtAll() {
        var ran: [String] = []
        let outcome = TerminalLauncher.launch(
            command: #"claude --resume x" & ""#, cwd: nil,
            ghosttyInstalled: true, run: { ran.append($0); return true }
        )
        XCTAssertEqual(outcome, .clipboard)
        XCTAssertTrue(ran.isEmpty, "no AppleScript may be built from unvalidated input")
    }
}
