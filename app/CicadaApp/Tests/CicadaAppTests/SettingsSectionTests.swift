import XCTest
@testable import CicadaApp

/// G122/G126 — Settings became a five-section `NavigationSplitView` sidebar
/// in place of the old four-tab `TabView`. `SettingsSection`'s raw values are
/// machine keys (R7), never the display string, so a `Copy.swift` rename can
/// never desync `@AppStorage("cicada.settingsSection")`'s persisted identity.
///
/// Track P adds two more properties of that same window: the persisted
/// section is mirrored in BOTH directions (recent-work #9 — a seed written
/// while Settings is already open was never read back), and the window's own
/// frame scales with `CicadaTheme.uiScale` like every token inside it does
/// (recent-work #11 — G130 grew the contents past a fixed 900×640).
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

    /// recent-work #9 — `EmptyStateView`'s "Open Integrations" seeds
    /// `UserDefaults["cicada.settingsSection"]` in a `.simultaneousGesture`
    /// and relies on `SettingsScene`'s `.onAppear` to read it. `onAppear`
    /// fires once per view lifetime, and Settings is a separate window that
    /// is very often ALREADY open — so the seed was written and never read,
    /// and the person landed on whatever section they last used.
    ///
    /// A source-text check, exactly like `testSettingsSceneUsesANavigationSplitView`
    /// above: `@AppStorage`'s KVO-driven republish is what makes this work at
    /// runtime, and there is no ViewInspector-free way to observe a SwiftUI
    /// `.onChange` from this suite — so the regression net is that the
    /// mirror stays SYMMETRIC (a write on `selection`, a read on
    /// `sectionRaw`), which is the thing that was missing.
    func testSettingsSceneMirrorsTheStoredSectionBackOntoSelection() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/Views/Settings/SettingsScene.swift")
        let text = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(text.contains("onChange(of: selection)"), "the write half")
        XCTAssertTrue(text.contains("onChange(of: sectionRaw)"), "the read half — recent-work #9")
    }

    /// recent-work #11 — `SettingsScene` and `FirstRunSheet` pin fixed frames
    /// while every font and spacing token inside them scales with
    /// `CicadaTheme.uiScale` (G130). At the top of `ThemeStore.scaleRange`
    /// (1.4) the sheet's footer — which is NOT inside its ScrollView — is the
    /// first thing to clip.
    func testWindowFramesScaleWithUiScale() {
        let previous = CicadaTheme.uiScale
        defer { CicadaTheme.uiScale = previous }
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(SettingsScene.windowWidth, 900, accuracy: 0.5)
        XCTAssertEqual(FirstRunSheet.sheetWidth, 780, accuracy: 0.5)
        // 1.4 is `ThemeStore.scaleRange.upperBound`; the setter snaps to the
        // nearest 0.1 step and clamps, so this is a value it really holds.
        CicadaTheme.uiScale = 1.4
        XCTAssertEqual(SettingsScene.windowWidth, 1260, accuracy: 1.0)
        XCTAssertEqual(SettingsScene.windowHeight, 896, accuracy: 1.0)
        XCTAssertEqual(FirstRunSheet.sheetWidth, 1092, accuracy: 1.0)
        XCTAssertEqual(FirstRunSheet.sheetHeight, 896, accuracy: 1.0)
    }
}
