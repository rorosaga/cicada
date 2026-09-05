import XCTest
@testable import CicadaApp

/// The sidebar gear opened nothing for weeks, and nothing in the code looked
/// wrong: it sent `showSettingsWindow:` through `NSApp.sendAction`, which on
/// macOS 26 returns `true` (SwiftUI's AppDelegate is the target) and then does
/// not create a window. A private selector that is accepted and ignored gives a
/// caller no signal to check, so this cannot be caught by asserting on a return
/// value — only by not using it.
///
/// A source lint is a blunt instrument, but a window opening is not unit
/// testable, and this encodes the one thing a future reader needs: the fix is
/// `SettingsLink`, and reaching for the selector again reintroduces a dead
/// button that looks fine in review.
final class SettingsEntryPointTests: XCTestCase {
    private func sourceFiles() throws -> [URL] {
        // …/Tests/CicadaAppTests/<this file> → …/Sources/CicadaApp
        let sources = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .appendingPathComponent("Sources/CicadaApp")
        let all = FileManager.default.enumerator(at: sources, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL }
            .filter { $0.pathExtension == "swift" } ?? []
        XCTAssertFalse(all.isEmpty, "found no sources under \(sources.path) — the lint would pass vacuously")
        return all
    }

    func testNoPrivateSettingsSelector() throws {
        for file in try sourceFiles() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for selector in ["showSettingsWindow:", "showPreferencesWindow:"] {
                XCTAssertFalse(
                    text.contains("Selector((\"\(selector)\""),
                    "\(file.lastPathComponent) sends the private selector \(selector). "
                    + "It is accepted and ignored on macOS 26 — open the Settings scene with SettingsLink."
                )
            }
        }
    }

    /// The gear is the only in-app way to reach Settings besides ⌘, so if this
    /// disappears, the entry point is gone with it.
    func testTheSidebarStillCarriesASettingsLink() throws {
        let sidebar = try sourceFiles().first { $0.lastPathComponent == "SidebarView.swift" }
        let text = try String(contentsOf: try XCTUnwrap(sidebar), encoding: .utf8)
        XCTAssertTrue(text.contains("SettingsLink"), "the sidebar footer no longer opens Settings")
    }

    /// G130 R5: the View menu (Zoom In/Out/Actual Size) is a `CommandGroup`
    /// on the app's own `Scene`, not a view-local shortcut — a source lint
    /// because a `Scene`'s `.commands` isn't something a unit test can
    /// render and inspect the menu bar for.
    func testTheAppStillCarriesTheZoomCommandGroup() throws {
        let appFile = try sourceFiles().first { $0.lastPathComponent == "CicadaApp.swift" }
        let text = try String(contentsOf: try XCTUnwrap(appFile), encoding: .utf8)
        XCTAssertTrue(
            text.contains("CommandGroup(after: .sidebar)"),
            "CicadaApp.swift no longer declares the View menu's zoom CommandGroup"
        )
    }
}
