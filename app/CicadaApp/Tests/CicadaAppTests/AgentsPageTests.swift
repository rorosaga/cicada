import XCTest
@testable import CicadaApp

/// G139 / A1 / R-O11 / R-O12 — From anywhere is a row of its own, Agents is
/// about this Mac.
final class AgentsPageTests: XCTestCase {
    private func source(_ relative: String) throws -> String {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp")
        return try String(contentsOf: root.appendingPathComponent(relative), encoding: .utf8)
    }

    func testFromAnywhereIsItsOwnCustomizeRow() {
        XCTAssertEqual(SettingsSection.remote.rawValue, "remote")
        XCTAssertEqual(SettingsSection.remote.group, .customize)
        // A prefix, not the whole list: Task 8 appends Skills, and
        // `RecommendedSkillTests.testSkillsIsACustomizeRow` pins the full group then.
        XCTAssertEqual(Array(SettingsGroup.customize.sections.prefix(3)), [.integrations, .agents, .remote])
        XCTAssertEqual(SettingsSection.remote.title, Copy.fromAnywhere)
        XCTAssertEqual(Copy.settingsFromAnywhere, "\(Copy.settings) → \(Copy.fromAnywhere)")
    }

    /// Someone who left Agents on its old "From anywhere" segment reopens there.
    func testTheRetiredSegmentMapsOntoTheNewRowOnce() {
        XCTAssertEqual(SettingsSection.restored(from: "agents", legacyAgentsMode: "anywhere"), .remote)
        XCTAssertEqual(SettingsSection.restored(from: "agents", legacyAgentsMode: "thisMac"), .agents)
        XCTAssertEqual(SettingsSection.restored(from: "sleep", legacyAgentsMode: "anywhere"), .sleep)
        XCTAssertEqual(SettingsSection.restored(from: nil, legacyAgentsMode: nil), .general)
    }

    func testTrackRsViewIsHostedNotRewritten() throws {
        XCTAssertTrue(try source("Views/Settings/FromAnywhereView.swift").contains("RemoteAccessView()"))
        let connect = try source("Views/Connect/ConnectView.swift")
        XCTAssertFalse(connect.contains("RemoteAccessView"), "the segment swap is gone")
        XCTAssertFalse(connect.contains("cicada.agentsMode"))
        XCTAssertFalse(connect.contains("pickerStyle(.segmented)"))
        XCTAssertFalse(connect.contains("isOnboarding"), "no caller since G117 (R-O11)")
    }

    func testAgentsAreDisclosureRowsThatLandingOpens() throws {
        let connect = try source("Views/Connect/ConnectView.swift")
        XCTAssertTrue(connect.contains(".settingsRow(.agent(agent.id))"))
        XCTAssertTrue(connect.contains("landedNonce"), "landing on agent:<id> opens that row")
    }
}
