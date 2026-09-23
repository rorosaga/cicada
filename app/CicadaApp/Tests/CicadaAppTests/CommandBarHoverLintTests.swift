import XCTest

/// DS-1 live check (2026-09-24): an `.onHover` above the command bar's search Button made
/// AppKit drop the principal toolbar item on macOS 26 — no bar, and no memory-bank selector,
/// with no error anywhere. `.onContinuousHover` renders. A unit test cannot see AppKit's
/// toolbar, so this pins the one spelling that was proven to work.
final class CommandBarHoverLintTests: XCTestCase {
    func testTheCommandBarNeverUsesOnHover() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/Views/Shell/CommandBar.swift")
        let source = try String(contentsOf: url, encoding: .utf8)
        let code = source.split(separator: "\n").filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
        XCTAssertFalse(code.contains { $0.contains(".onHover") },
                       "Use .onContinuousHover in CommandBar — .onHover drops the toolbar item on macOS 26")
        XCTAssertTrue(source.contains(".onContinuousHover"), "the bar's hover ring must still track the pointer")
    }
}
