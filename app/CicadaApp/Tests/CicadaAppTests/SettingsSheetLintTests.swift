import XCTest
@testable import CicadaApp

/// R-HS16 — Settings raises sheets, never popovers. The panel is modal and inset 40 pt, so a
/// popover anchored to a row near its edge could open past the screen (owner-reported: Manage).
/// AppKit centres a sheet on its window.
final class SettingsSheetLintTests: XCTestCase {
    private func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    func testNothingUnderSettingsRaisesAPopover() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where file.path.contains("/Views/Settings/") {
            let lines = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            for (i, line) in lines.enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && line.contains(".popover(") {
                offenders.append("\(file.lastPathComponent):\(i + 1)")
            }
        }
        XCTAssertEqual(offenders, [])
    }

    func testEveryManageAndConnectIsASettingsSheet() throws {
        for suffix in ["Views/Settings/LocalSourceRows.swift", "Views/Settings/IntegrationsView.swift"] {
            let text = try source(suffix)
            XCTAssertTrue(text.contains(".sheet("), suffix)
            XCTAssertTrue(text.contains("SettingsSheet("), suffix)
        }
    }

    /// The owner's report: labels, not placeholders, and no glob typed by hand.
    func testTheAddFolderSheetHasLabelsAndNoGlobField() throws {
        let text = try source("Views/Settings/LocalSourceRows.swift")
        XCTAssertFalse(text.contains("\"archive/**\""), "the default is a pre-ticked folder, not a typed glob")
        XCTAssertFalse(text.contains("TextField(\"Parts written by an agent\""))
        XCTAssertTrue(text.contains("AgentFolderPicker("))
        XCTAssertTrue(text.contains("LabeledField("))
    }
}
