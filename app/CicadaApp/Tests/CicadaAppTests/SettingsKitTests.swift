import XCTest
@testable import CicadaApp

/// G139 (Settings v3) — the kit every page is built from. Pure facts and
/// source lints: a SwiftUI layout is not unit-testable here, the rules that
/// make it right are.
final class SettingsKitTests: XCTestCase {

    private func source(_ relative: String) throws -> String {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp")
        return try String(contentsOf: root.appendingPathComponent(relative), encoding: .utf8)
    }

    // MARK: Groups (R-O3, spec decision 17)

    func testEverySectionIsInExactlyOneGroupInDeclarationOrder() {
        XCTAssertEqual(SettingsGroup.allCases.flatMap(\.sections), SettingsSection.allCases,
                       "a section missing from a group, in two, or declared out of sidebar order")
    }

    func testGroupTitlesComeFromCopy() {
        XCTAssertEqual(SettingsGroup.cicada.title, Copy.groupCicada)
        XCTAssertEqual(SettingsGroup.customize.title, Copy.groupCustomize)
        XCTAssertEqual(SettingsGroup.enginesAndKeys.title, Copy.groupEnginesAndKeys)
    }

    // MARK: Row ids

    func testRowIdEncodings() {
        XCTAssertEqual(SettingsRowID.page(.sleep).rawValue, "page:sleep")
        XCTAssertEqual(SettingsRowID.channel("pinterest").rawValue, "channel:pinterest")
        XCTAssertEqual(SettingsRowID.agent("codex").item(of: "agent"), "codex")
        XCTAssertNil(SettingsRowID.textSize.item(of: "agent"))
        XCTAssertEqual(SettingsRowID.skill("watch").item(of: "skill"), "watch")
    }

    // MARK: Focus (R-O6, R-O7)

    @MainActor
    func testGoStagesARequestWithAFreshNonce() {
        let focus = SettingsFocus()
        focus.go(.sleep)
        let first = focus.request
        focus.go(.sleep)
        XCTAssertEqual(first?.section, .sleep)
        XCTAssertNotEqual(first, focus.request, "the same section twice must still re-land")
    }

    @MainActor
    func testLandingHighlightsScrollsAndIsConsumedOnce() {
        let focus = SettingsFocus()
        focus.land(on: .textSize, announcing: "General, Text size", reduceMotion: true)
        XCTAssertEqual(focus.highlighted, .textSize)
        XCTAssertEqual(focus.scrollTarget, .textSize)
        XCTAssertEqual(focus.landed, .textSize)
        focus.consumeScroll()
        XCTAssertNil(focus.scrollTarget, "a page appearing later must not jump to an old target")
        XCTAssertEqual(focus.highlighted, .textSize, "the wash outlives the scroll")
    }

    func testHighlightTimingIsTheDesignsAndReduceMotionDropsTheFade() {
        XCTAssertEqual(CicadaMotion.rowHighlightHold, 1.2, accuracy: 0.001)
        XCTAssertEqual(CicadaMotion.rowHighlightFadeDuration, 0.6, accuracy: 0.001)
        XCTAssertNil(CicadaMotion.rowHighlightFade(reduceMotion: true))
        XCTAssertNotNil(CicadaMotion.rowHighlightFade(reduceMotion: false))
    }

    // MARK: Source lints

    func testEveryRowIsAnAnchor() throws {
        XCTAssertTrue(try source("Views/Settings/SettingsRow.swift").contains(".settingsRow(id)"),
                      "SettingsRow must apply its own anchor, or search cannot land on it")
    }

    func testPillPickerExposesARealPickerToAccessibility() throws {
        XCTAssertTrue(try source("Views/Common/PillPicker.swift").contains(".accessibilityRepresentation"))
    }

    func testTheSidebarGlyphsAcknowledgeHover() throws {
        XCTAssertTrue(try source("Views/Settings/SettingsScene.swift").contains(".iconHover("))
    }

    func testSettingsContentNeverUsesGlass() throws {
        for file in ["Views/Settings/SettingsRow.swift", "Views/Settings/SettingsDetailHeader.swift",
                     "Views/Common/PillPicker.swift"] {
            let text = try source(file)
            XCTAssertFalse(text.contains("liquidGlass("), file)
            XCTAssertFalse(text.contains(".glassCard("), file)
        }
    }
}
