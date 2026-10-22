import XCTest
@testable import CicadaApp

/// G139 / A1 / R-O11 / R-O12 — From anywhere is not part of Agents, which is about this Mac. Since the Hyrum audit's
/// B1 it is a group on Devices & access.
final class AgentsPageTests: XCTestCase {
    private func source(_ relative: String) throws -> String {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp")
        return try String(contentsOf: root.appendingPathComponent(relative), encoding: .utf8)
    }

    /// Hyrum audit B1 (2026-10-22): From anywhere is a group on Devices & access; its old raw value opens there.
    func testFromAnywhereIsAGroupOnDevicesAndAccess() {
        XCTAssertNil(SettingsSection(rawValue: "remote"))
        XCTAssertEqual(SettingsSection.restored(from: "remote"), .devices)
        XCTAssertEqual(SettingsSection.retired["remote"]?.row, .fromAnywhere)
        XCTAssertEqual(SettingsSection.devices.group, .customize)
        XCTAssertEqual(Copy.settingsFromAnywhere, "\(Copy.settings) → \(Copy.Devices.sidebar) → \(Copy.fromAnywhere)")
    }

    /// Someone who left Agents on its old "From anywhere" segment reopens where From anywhere lives now.
    func testTheRetiredSegmentMapsOntoTheNewRowOnce() {
        XCTAssertEqual(SettingsSection.restored(from: "agents", legacyAgentsMode: "anywhere"), .devices)
        XCTAssertEqual(SettingsSection.restored(from: "agents", legacyAgentsMode: "thisMac"), .agents)
        XCTAssertEqual(SettingsSection.restored(from: "sleep", legacyAgentsMode: "anywhere"), .sleep)
        XCTAssertEqual(SettingsSection.restored(from: nil, legacyAgentsMode: nil), .general)
    }

    func testTrackRsViewIsHostedNotRewritten() throws {
        XCTAssertTrue(try source("Views/Settings/DevicesSettingsView.swift").contains("RemoteAccessView()"))
        let connect = try source("Views/Connect/ConnectView.swift")
        XCTAssertFalse(connect.contains("RemoteAccessView"), "the segment swap is gone")
        XCTAssertFalse(connect.contains("cicada.agentsMode"))
        XCTAssertFalse(connect.contains("pickerStyle(.segmented)"))
        XCTAssertFalse(connect.contains("isOnboarding"), "no caller since G117 (R-O11)")
    }

    func testAgentsAreASelectorThatLandingSelects() throws {
        let connect = try source("Views/Connect/ConnectView.swift")
        XCTAssertTrue(connect.contains("AgentSelector("))
        XCTAssertTrue(connect.contains("AgentSetupSteps("))
        XCTAssertTrue(connect.contains(".settingsRow(.agent(selected))"))
        XCTAssertTrue(connect.contains("landedNonce"), "landing on agent:<id> selects that pill")
        XCTAssertTrue(connect.contains("live.run()"), "the ✓ is polled while the page is visible (R-AG15)")
    }
}
