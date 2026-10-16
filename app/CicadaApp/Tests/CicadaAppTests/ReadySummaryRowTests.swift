import XCTest
@testable import CicadaApp

/// QA 2026-10-16 — You're set's summary showed an empty row with only "Waits in the menu bar" at its far edge when no
/// agent was connected. The startup word leads when there is no agents line.
final class ReadySummaryRowTests: XCTestCase {
    func testTheStartupWordLeadsWithoutAgents() throws {
        let row = try XCTUnwrap(ReadyPage.lastRow(agents: nil, startup: "Waits in the menu bar"))
        XCTAssertEqual(row.lead, "Waits in the menu bar")
        XCTAssertNil(row.trail)
    }

    func testTheAgentsLineLeadsAndTheStartupWordTrails() throws {
        let row = try XCTUnwrap(ReadyPage.lastRow(agents: "Claude Code connected", startup: "Waits in the menu bar"))
        XCTAssertEqual(row.lead, "Claude Code connected")
        XCTAssertEqual(row.trail, "Waits in the menu bar")
    }

    func testNothingToSayIsNoRow() {
        XCTAssertNil(ReadyPage.lastRow(agents: nil, startup: nil))
    }
}
