import XCTest
@testable import CicadaApp

/// G137 — the sidebar is the chrome this track reskins. Source checks, the
/// house shape for layout rules a unit test cannot render and ask
/// (`SettingsEntryPointTests`).
final class SidebarChromeTests: XCTestCase {
    private func sidebar() throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "SidebarView.swift" })
        return try String(contentsOf: file, encoding: .utf8)
    }

    /// WWDC25-323: "extra backgrounds … behind the bar items … interfere with
    /// the effect". The opaque fill covered macOS 26's floating glass sidebar.
    func testTheSidebarLetsTheSystemGlassThroughOnMacOS26() throws {
        let text = try sidebar()
        XCTAssertTrue(text.contains(".sidebarChromeBackground()"))
        XCTAssertFalse(text.contains(".background(CicadaTheme.background)"))
    }

    /// The owner: "Add animations to the icons as i hover over them."
    func testEveryTabGlyphAcknowledgesThePointerAndItsSelection() throws {
        XCTAssertTrue(try sidebar().contains(".iconHover(hovering: isHovered, selected: isSelected)"))
    }

    /// `.white` is 2.53:1 on the new dark accent (R-M11).
    func testTheBadgeInkIsAToken() throws {
        let text = try sidebar()
        XCTAssertFalse(text.contains(".foregroundStyle(.white)"))
        XCTAssertTrue(text.contains("CicadaTheme.onAccent"))
    }
}
