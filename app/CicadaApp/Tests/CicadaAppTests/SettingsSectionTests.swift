import XCTest
@testable import CicadaApp

/// G122/G126 — Settings is a sidebar of sections, not a tab bar; since DR-33 that sidebar
/// lives in the in-app panel (`SettingsPanel`, pinned by `SettingsPanelTests`), which replaced
/// the scene's `NavigationSplitView`. `SettingsSection`'s raw values are machine keys (R7),
/// never the display string, so a `Copy.swift` rename can never desync
/// `@AppStorage("cicada.settingsSection")`'s persisted identity.
///
/// Track P's two window properties (the two-way section mirror, the uiScale-scaled frame)
/// retired with the window: nothing crosses a window any more (R-DS22), and the panel's size
/// is `SettingsPanelLayout.size(container:)`, which `SettingsPanelTests` pins at 1× and 1.4×.
final class SettingsSectionTests: XCTestCase {

    func testRestoredFallsBackToGeneral() {
        XCTAssertEqual(SettingsSection.restored(from: nil), .general)
        XCTAssertEqual(SettingsSection.restored(from: "bogus"), .general)
        XCTAssertEqual(SettingsSection.restored(from: "sleep"), .sleep)
    }

    func testEveryTitleComesFromCopy() {
        XCTAssertEqual(SettingsSection.general.title, Copy.general)
        XCTAssertEqual(SettingsSection.sleep.title, Copy.sleepSettings)
        XCTAssertEqual(SettingsSection.intelligence.title, Copy.Intelligence.title)
        XCTAssertEqual(SettingsSection.you.title, Copy.youSection)
        XCTAssertEqual(SettingsSection.privacy.title, Copy.privacyAndData)
        XCTAssertEqual(SettingsSection.devices.title, Copy.Devices.sidebar)
    }

    /// R7 / K1 — a persisted selection must survive Settings v3.
    func testExistingRawValuesAreStable() {
        XCTAssertEqual(SettingsSection.general.rawValue, "general")
        XCTAssertEqual(SettingsSection.sleep.rawValue, "sleep")
        XCTAssertEqual(SettingsSection.devices.rawValue, "devices")
        XCTAssertEqual(SettingsSection.privacy.rawValue, "privacy")
        XCTAssertEqual(SettingsSection.intelligence.rawValue, "intelligence")
    }

    func testEverySubtitleComesFromCopyAndNoIconImpliesAPrice() {
        // D6's word budget: no section carries a subtitle.
        XCTAssertEqual(SettingsSection.general.subtitle, "")
        XCTAssertFalse(SettingsSection.allCases.map(\.icon).contains("creditcard"), "K4 — creditcard implies a price")
    }
}
