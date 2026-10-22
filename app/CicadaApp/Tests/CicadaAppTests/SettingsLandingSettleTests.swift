import XCTest
@testable import CicadaApp

/// Hyrum audit B1 review — a landing keeps its row on screen while the page's late cards arrive, inside a bound, and
/// lets go the moment the person takes over. `SettingsScroll` lands again on each `settleNonce`.
@MainActor
final class SettingsLandingSettleTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_000_000)

    private func landed(on row: SettingsRowID = .commandLineTool) -> SettingsFocus {
        let focus = SettingsFocus()
        focus.land(on: row, announcing: "Agents, Command-line tool", reduceMotion: true, now: start)
        return focus
    }

    func testTheRowsFirstPlaceAndEachMoveLandAgain() {
        let focus = landed()
        XCTAssertEqual(focus.settling, .commandLineTool)
        focus.settlingRowMoved(.commandLineTool, contentY: 400, now: start.addingTimeInterval(0.1))
        XCTAssertEqual(focus.settleNonce, 1, "the row's first report: it may not have existed at the first scroll")
        focus.settlingRowMoved(.commandLineTool, contentY: 400, now: start.addingTimeInterval(0.2))
        XCTAssertEqual(focus.settleNonce, 1, "unmoved: nothing to do")
        focus.settlingRowMoved(.commandLineTool, contentY: 1_300, now: start.addingTimeInterval(1.5))
        XCTAssertEqual(focus.settleNonce, 2, "a late card above pushed it down: land again")
    }

    func testAnotherRowsMoveIsIgnored() {
        let focus = landed()
        focus.settlingRowMoved(.agentsCloud, contentY: 900, now: start.addingTimeInterval(0.1))
        XCTAssertEqual(focus.settleNonce, 0)
    }

    func testTheWindowEnds() {
        let focus = landed()
        let after = start.addingTimeInterval(CicadaMotion.settingsLandingWindow + 0.1)
        focus.settlingRowMoved(.commandLineTool, contentY: 1_300, now: after)
        XCTAssertEqual(focus.settleNonce, 0, "past the bound the page is the person's")
        XCTAssertNil(focus.settling)
    }

    func testThePersonTakingOverEndsIt() {
        let focus = landed()
        focus.endSettle()   // a scroll, a key, a new search or a sidebar pick
        focus.settlingRowMoved(.commandLineTool, contentY: 1_300, now: start.addingTimeInterval(0.5))
        XCTAssertEqual(focus.settleNonce, 0, "never pulled back after the person scrolled")
        XCTAssertNil(focus.settling)
    }

    func testANewerLandingReplacesTheOld() {
        let focus = landed()
        focus.land(on: .fromAnywhere, announcing: "Devices & access, From anywhere", reduceMotion: true,
                   now: start.addingTimeInterval(1))
        XCTAssertEqual(focus.settling, .fromAnywhere)
        focus.settlingRowMoved(.commandLineTool, contentY: 1_300, now: start.addingTimeInterval(1.2))
        XCTAssertEqual(focus.settleNonce, 0)
    }

    /// The panel ends the settle on a new query and a sidebar pick; the scroll lands again without animating.
    func testThePanelEndsItAndTheScrollNeverAnimates() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp/Views/Settings")
        let panel = try String(contentsOf: root.appendingPathComponent("SettingsPanel.swift"), encoding: .utf8)
        XCTAssertEqual(panel.components(separatedBy: "focus.endSettle()").count - 1, 2, "query change and sidebar pick")
        let scroll = try String(contentsOf: root.appendingPathComponent("SettingsFocus.swift"), encoding: .utf8)
        let settle = try XCTUnwrap(scroll.range(of: "focus?.settleNonce"))
        XCTAssertFalse(scroll[settle.lowerBound...].prefix(300).contains("withAnimation"), "DR-60")
    }
}
