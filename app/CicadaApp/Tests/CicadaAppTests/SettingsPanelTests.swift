import XCTest
@testable import CicadaApp

/// DR-33 — the owner (2026-09-23): "a window inside the app, like the one in claude desktop
/// app". A panel over the dimmed main window, never a second window.
@MainActor
final class SettingsPanelTests: XCTestCase {
    override func tearDown() { CicadaTheme.uiScale = 1.0; super.tearDown() }

    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
    }

    /// 880 × 620 at the rules' window (content 1440 × 848 under the 52 pt titlebar), inset ≥ 40 at
    /// the smallest, and it scales with the chrome without ever leaving the window.
    func testThePanelsSize() {
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(SettingsPanelLayout.size(container: CGSize(width: 1440, height: 848)), CGSize(width: 880, height: 620))
        XCTAssertEqual(SettingsPanelLayout.size(container: CGSize(width: 1200, height: 748)), CGSize(width: 880, height: 620))
        CicadaTheme.uiScale = 1.4
        let zoomed = SettingsPanelLayout.size(container: CGSize(width: 1200, height: 748))
        XCTAssertEqual(zoomed.width, 1120, accuracy: 0.5, "1200 − 2 × 40")
        XCTAssertEqual(zoomed.height, 668, accuracy: 0.5, "748 − 2 × 40")
        XCTAssertEqual(SettingsPanelLayout.size(container: .zero), .zero)
    }

    func testThePanelLivesInTheMainWindowNotAScene() throws {
        let app = try source("CicadaApp.swift")
        XCTAssertFalse(app.contains("Settings {"), "the scene is gone — ⌘, can never open a second window")
        XCTAssertTrue(app.contains("WindowGroup(id: Self.mainWindowID)"))
        let content = try source("ContentView.swift")
        XCTAssertTrue(content.contains("SettingsPanel()"))
        XCTAssertTrue(content.contains("router.settingsOpen"))
        XCTAssertFalse(try ThemeTokenTests.swiftSources().contains { $0.lastPathComponent == "SettingsScene.swift" })
    }

    /// R-DS21 — Esc closes through the visible close control's `.cancelAction`, and the panel's
    /// own search field hands Esc to the same close instead of clearing itself first. Both go
    /// through `SettingsFocus.escape`, so an open sub-page goes back first (R-O5).
    func testEscClosesThroughAVisibleControl() throws {
        let text = try source("Views/Settings/SettingsPanel.swift")
        XCTAssertTrue(text.contains("shortcut: .cancelAction"))
        XCTAssertTrue(text.contains("router.closeSettings()"))
        XCTAssertTrue(text.contains("onEscape: { focus.escape { router.closeSettings() } }"),
                      "the focused search field would otherwise answer Esc itself (clear, then blur)")
        XCTAssertTrue(text.contains("shortcut: .cancelAction) { focus.escape { router.closeSettings() } }"),
                      "R-O5 — the ×'s key equivalent backs out of a sub-page before it closes")
        let detail = try source("Views/Settings/SkillDetailView.swift")
        XCTAssertFalse(detail.contains(".onExitCommand"),
                       "the ×'s .cancelAction pre-empts it; Esc goes back through SettingsFocus.escapeBack")
        XCTAssertTrue(try source("Views/Settings/SkillsView.swift").contains("focus?.escapeBack ="))
    }

    /// G139 survives the move: the search field, the groups, the index, the results, the hover.
    func testTheSidebarKeepsG139() throws {
        let text = try source("Views/Settings/SettingsPanel.swift")
        for needle in ["CicadaSearchField(", "SettingsGroup.allCases", "SettingsIndex.search(", "SettingsResultsView(",
                       ".iconHover(", "SectionLabel(group.title)"] {
            XCTAssertTrue(text.contains(needle), needle)
        }
        XCTAssertFalse(text.contains("NavigationSplitView"))
        XCTAssertFalse(text.contains("List(selection:"), "List selection paints the accent (DR-22)")
    }

    /// R-DS22 — the selection is remembered per viewer by the panel alone; a request is consumed.
    func testTheSelectionIsTheirsAndARequestIsConsumed() throws {
        let text = try source("Views/Settings/SettingsPanel.swift")
        XCTAssertTrue(text.contains(#"@AppStorage("cicada.settingsSection")"#))
        XCTAssertTrue(text.contains("onChange(of: selection)"))
        XCTAssertTrue(text.contains("router.consumeSettings()"))
    }

    /// DR-13 — no header wash, no nature token on a row.
    func testNoMeadowOnTheSettingsChrome() throws {
        XCTAssertFalse(try source("Views/Settings/SettingsDetailHeader.swift").contains("skyWash"))
        let focus = try source("Views/Settings/SettingsFocus.swift")
        XCTAssertFalse(focus.contains("dandelion"))
        XCTAssertTrue(focus.contains("CicadaTheme.focusRing"))
    }
}
