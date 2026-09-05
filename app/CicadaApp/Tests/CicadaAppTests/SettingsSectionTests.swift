import XCTest
@testable import CicadaApp

/// G122/G126 — Settings became a five-section `NavigationSplitView` sidebar
/// in place of the old four-tab `TabView`. `SettingsSection`'s raw values are
/// machine keys (R7), never the display string, so a `Copy.swift` rename can
/// never desync `@AppStorage("cicada.settingsSection")`'s persisted identity.
final class SettingsSectionTests: XCTestCase {

    func testRestoredFallsBackToGeneral() {
        XCTAssertEqual(SettingsSection.restored(from: nil), .general)
        XCTAssertEqual(SettingsSection.restored(from: "bogus"), .general)
        XCTAssertEqual(SettingsSection.restored(from: "sleep"), .sleep)
    }

    func testEveryTitleComesFromCopy() {
        XCTAssertEqual(SettingsSection.general.title, Copy.general)
        XCTAssertEqual(SettingsSection.sleep.title, Copy.sleepSettings)
        XCTAssertEqual(SettingsSection.integrations.title, Copy.integrations)
        XCTAssertEqual(SettingsSection.agents.title, Copy.agents)
        XCTAssertEqual(SettingsSection.plansAndKeys.title, Copy.plansAndKeys)
    }

    /// A source-text check rather than a runtime one: `NavigationSplitView`
    /// has no reliable ViewInspector-free runtime signature, so this greps
    /// the file directly the way `FontLiteralLintTests` already does for its
    /// own banned literal.
    func testSettingsSceneUsesANavigationSplitView() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/Views/Settings/SettingsScene.swift")
        let text = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(text.contains("NavigationSplitView"))
    }
}
