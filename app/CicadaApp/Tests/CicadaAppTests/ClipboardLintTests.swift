import AppKit
import XCTest
@testable import CicadaApp

/// 2026-09-24: running `swift test` replaced the owner's clipboard with a fixture's
/// `claude --resume 0f8f1c2a-…` — `TerminalLauncher`'s clipboard fallback and `copyCommand` wrote
/// `NSPasteboard.general` from inside the test process. Every clipboard access now goes through
/// `AppPasteboard`, which is a private pasteboard under XCTest; this lint keeps it the only door.
final class ClipboardLintTests: XCTestCase {
    static let home = "Support/AppPasteboard.swift"

    func testOnlyAppPasteboardTouchesTheSystemClipboard() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where !file.path.hasSuffix(Self.home) {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//"), !code.hasPrefix("///") else { continue }
                if code.contains("NSPasteboard.general") || code.contains("NSPasteboard(name: .general") {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "use AppPasteboard — a test run must never touch the person's clipboard")
    }

    func testUnderTestsTheDoorIsAPrivatePasteboard() {
        XCTAssertTrue(AppPasteboard.isRunningTests)
        XCTAssertNotEqual(AppPasteboard.board.name, NSPasteboard.general.name)
    }

    /// The exact path that leaked: every rung failing falls back to the clipboard.
    func testTheTerminalFallbackNeverWritesTheSystemClipboard() {
        let before = NSPasteboard.general.changeCount
        let outcome = TerminalLauncher.launch(command: "claude --resume 0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b",
                                              cwd: nil, ghosttyInstalled: true, run: { _ in false })
        XCTAssertEqual(outcome, .clipboard)
        XCTAssertEqual(NSPasteboard.general.changeCount, before, "the person's clipboard changed during a test")
        XCTAssertEqual(AppPasteboard.board.string(forType: .string),
                       "claude --resume 0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b")
    }
}
