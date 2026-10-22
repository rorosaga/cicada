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
        let marks = ["header: Copy.lookGroup", "SettingsRow(.textSize,", "header: Copy.startupGroup",
                     "SettingsRow(.openAtLogin,", "SettingsRow(.showInMenuBar,", "header: Copy.whenClosedGroup",
                     "SettingsRow(.backgroundService,", "SettingsDemoTourGroup()", "SettingsRow(.appVersion,"]
        let positions = try marks.map { try XCTUnwrap(text.range(of: $0), $0).lowerBound }
        XCTAssertEqual(positions, positions.sorted(),
                       "F-10: Look · Startup · When Cicada is closed, then Getting started and the version (Hyrum B12)")
        XCTAssertTrue(try source("Views/Settings/SettingsDemoTourGroup.swift").contains("SettingsRow(.runSetup,"),
                      "Setup is in Getting started")
        XCTAssertEqual(Copy.lookGroup, "Look")
        XCTAssertEqual(Copy.startupGroup, "Startup")
        XCTAssertEqual(Copy.whenClosedGroup, "When Cicada is closed")
    }

    /// Scene retired with the painted art (owner 2026-10-16): there is no painting left to pick, so General has no
    /// Scene row and search finds none.
    func testTheSceneRowRetiredWithThePaintings() throws {
        let text = try source("Views/Settings/SettingsGeneralView.swift")
        XCTAssertFalse(text.contains("heroScene"))
        XCTAssertFalse(SettingsIndex.staticEntries.contains { $0.id.rawValue == "heroScene" })
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

    /// R-HO16 kept its rule — the rows never promise what the app does not do (R-FA7) — and R-OB18 made the quiet
    /// start true, so the login row now says it, split by the menu-bar switch.
    func testStartupWordsStayHonest() {
        XCTAssertTrue(Copy.loginItemQuiet(menuBarVisible: true).contains("no window"))
        XCTAssertTrue(Copy.loginItemQuiet(menuBarVisible: true).contains("menu bar"))
        XCTAssertFalse(Copy.loginItemQuiet(menuBarVisible: false).contains("menu bar"),
                       "with the bookworm hidden the Dock is what is left")
        XCTAssertEqual(LoginItemState.on.detail(menuBarVisible: true), Copy.loginItemQuiet(menuBarVisible: true))
        XCTAssertEqual(LoginItemState.needsApproval.detail(menuBarVisible: true), Copy.loginItemNeedsApproval)
        XCTAssertFalse(Copy.showInMenuBarDetail.lowercased().contains("no window"), Copy.showInMenuBarDetail)
        XCTAssertFalse(Copy.backgroundDetail(.running).lowercased().contains("calendar"), "the Calendar read is app-side (D2)")
        XCTAssertTrue(Copy.backgroundDetail(.running).contains("agents"))
    }

    func testTheCommandBarHasNoStackGlyph() throws {
        XCTAssertFalse(try source("Views/Shell/BankSwitcher.swift").contains("square.stack"), "decision 11 (R-HO17)")
    }
}
