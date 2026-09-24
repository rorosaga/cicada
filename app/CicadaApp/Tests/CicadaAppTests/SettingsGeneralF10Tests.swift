import XCTest
@testable import CicadaApp

/// F-10 (round-4 decisions 6, 8, 11; R-HO16, R-HO17) — Settings → General's groups and words, the new *Show in menu
/// bar*, and the command bar without its stack glyph.
@MainActor
final class SettingsGeneralF10Tests: XCTestCase {
    private func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    func testGeneralIsF10sGroupsInOrder() throws {
        let text = try source("Views/Settings/SettingsGeneralView.swift")
        let marks = ["header: Copy.lookGroup", "SettingsRow(.heroScene,", "header: Copy.startupGroup",
                     "SettingsRow(.openAtLogin,", "SettingsRow(.showInMenuBar,", "header: Copy.whenClosedGroup",
                     "SettingsRow(.backgroundService,", "SettingsRow(.runSetup,"]
        let positions = try marks.map { try XCTUnwrap(text.range(of: $0), $0).lowerBound }
        XCTAssertEqual(positions, positions.sorted(), "F-10: Look · Startup · When Cicada is closed · Setup")
        XCTAssertEqual(Copy.lookGroup, "Look")
        XCTAssertEqual(Copy.startupGroup, "Startup")
        XCTAssertEqual(Copy.whenClosedGroup, "When Cicada is closed")
    }

    func testTheSceneRowSaysWhatItShowsNowAndHowItWorks() {
        XCTAssertEqual(SceneTime.allCases.map(Copy.sceneNow), ["Day now", "Afternoon now", "Night now"])
        XCTAssertEqual(Copy.sceneDetail, "The meadow on Home and in setup")
        XCTAssertTrue(Copy.sceneAutomaticExplainer.contains("no location needed"))
        XCTAssertTrue(Copy.sceneCrossfadeExplainer.contains("crossfades"))
    }

    func testShowInMenuBarIsARealIndexedRow() {
        XCTAssertTrue(SettingsIndex.staticIDs.contains(.showInMenuBar))
        let entry = SettingsIndex.staticEntries.first { $0.id == .showInMenuBar }
        XCTAssertNotNil(entry)
        XCTAssertEqual(Copy.showInMenuBar, "Show in menu bar", "F-10's words, the same as onboarding's F-06")
    }

    func testTheMenuBarPreferenceDefaultsToShown() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "cicada.test.menubar.\(UUID().uuidString)"))
        XCTAssertTrue(MenuBarPreference.isVisible(defaults))
        defaults.set(false, forKey: MenuBarPreference.defaultsKey)
        XCTAssertFalse(MenuBarPreference.isVisible(defaults))
    }

    func testTheManagerHidesItsBookwormWithoutTearingItDown() {
        let manager = MenuBarManager()
        XCTAssertTrue(manager.isVisible)
        manager.setVisible(false)
        XCTAssertFalse(manager.isVisible)
    }

    func testTheAppAppliesTheSwitchAtLaunchAndOnChange() throws {
        let app = try source("CicadaApp.swift")
        XCTAssertTrue(app.contains("@AppStorage(MenuBarPreference.defaultsKey)"))
        XCTAssertTrue(app.contains(".onChange(of: menuBarVisible)"))
        XCTAssertTrue(app.contains("menuBarManager.setVisible(menuBarVisible)"))
    }

    /// R-HO16 — the rows never promise what the app does not do (R-FA7).
    func testStartupWordsStayHonest() {
        for text in [Copy.loginItemOn, Copy.loginItemOff, Copy.showInMenuBarDetail] {
            XCTAssertFalse(text.lowercased().contains("no window"), text)
        }
        XCTAssertFalse(Copy.backgroundDetail(.running).lowercased().contains("calendar"), "the Calendar read is app-side (D2)")
        XCTAssertTrue(Copy.backgroundDetail(.running).contains("agents"))
    }

    func testTheCommandBarHasNoStackGlyph() throws {
        XCTAssertFalse(try source("Views/Shell/BankSwitcher.swift").contains("square.stack"), "decision 11 (R-HO17)")
    }
}
