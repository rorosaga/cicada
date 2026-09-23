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
        XCTAssertEqual(SettingsSection.integrations.title, Copy.integrations)
        XCTAssertEqual(SettingsSection.agents.title, Copy.agents)
        XCTAssertEqual(SettingsSection.remote.title, Copy.fromAnywhere)
        XCTAssertEqual(SettingsSection.engines.title, Copy.engines)
        XCTAssertEqual(SettingsSection.plansAndKeys.title, Copy.plansAndKeys)
        XCTAssertEqual(SettingsSection.you.title, Copy.youSection)
        XCTAssertEqual(SettingsSection.privacy.title, Copy.privacyAndData)
        XCTAssertEqual(SettingsSection.memory.title, Copy.memorySection)
        XCTAssertEqual(SettingsSection.advanced.title, Copy.advanced)
        XCTAssertEqual(SettingsSection.skills.title, Copy.skills)
    }

    /// R7 / K1 — a persisted selection must survive Settings v3.
    func testExistingRawValuesAreStable() {
        XCTAssertEqual(SettingsSection.general.rawValue, "general")
        XCTAssertEqual(SettingsSection.sleep.rawValue, "sleep")
        XCTAssertEqual(SettingsSection.integrations.rawValue, "integrations")
        XCTAssertEqual(SettingsSection.agents.rawValue, "agents")
        XCTAssertEqual(SettingsSection.plansAndKeys.rawValue, "plansAndKeys")
    }

    func testEverySubtitleComesFromCopyAndPlansAndKeysNoLongerImpliesAPrice() {
        XCTAssertEqual(SettingsSection.general.subtitle, Copy.generalSubtitle)
        XCTAssertEqual(SettingsSection.plansAndKeys.subtitle, Copy.plansAndKeysSubtitle)
        XCTAssertEqual(SettingsSection.plansAndKeys.icon, "key.horizontal", "K4 — creditcard implies a price")
    }
}
