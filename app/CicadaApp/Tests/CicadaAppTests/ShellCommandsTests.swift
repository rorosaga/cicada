import XCTest
@testable import CicadaApp

/// R-DS15 / R-DS16 — the shell's menu commands, and a titlebar AppKit keeps owning.
final class ShellCommandsTests: XCTestCase {
    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
    }

    func testTheSidebarToggleIsAViewCommandWithTheSystemShortcut() throws {
        let text = try source("Support/ShellCommands.swift")
        XCTAssertTrue(text.contains("CommandGroup(before: .sidebar)"))
        // Apple: the `.sidebar` group also holds Enter/Exit Full Screen — replacing it drops full screen.
        XCTAssertFalse(text.contains("CommandGroup(replacing: .sidebar)"), "R-DS15: never replace the system group")
        XCTAssertTrue(text.contains(#".keyboardShortcut("s", modifiers: [.control, .command])"#))
        XCTAssertTrue(text.contains("ShellMetrics.labelledKey"), "the same per-viewer key the rail reads")
    }

    func testTheAppHidesTheTitleAndInstallsTheCommands() throws {
        let app = try source("CicadaApp.swift")
        XCTAssertTrue(app.contains(".windowToolbarStyle(.unified(showsTitle: false))"), "DR-23: the title is hidden")
        XCTAssertTrue(app.contains("ShellCommands("))
    }

    /// DR-23 — the gaps drag the window because AppKit owns them. Nothing custom may take a
    /// mouse-down in the titlebar: a hand-rolled drag handler is how "the bar swallowed my drag"
    /// bugs start, and a hit-test cannot be unit-tested, so the lint pins the mechanism.
    func testTheTitlebarIsAToolbarAndNothingHandRollsADrag() throws {
        let content = try source("ContentView.swift")
        XCTAssertTrue(content.contains(".toolbar {"))
        XCTAssertTrue(content.contains("ShellToolbar("))
        for file in try ThemeTokenTests.swiftSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for needle in ["isMovableByWindowBackground", "performDrag(", "WindowDragGesture"] {
                XCTAssertFalse(text.contains(needle), "\(file.lastPathComponent) hand-rolls a window drag")
            }
        }
    }
}
