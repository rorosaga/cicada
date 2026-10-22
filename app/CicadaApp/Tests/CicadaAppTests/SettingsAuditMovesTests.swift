import XCTest
@testable import CicadaApp

/// The settings audit and ruling 36 D6 (2026-10-22): where your memory lives went from General to Devices, Sleep leads
/// with the study room, and Ask follows the engine on Intelligence. These hold the moves to
/// the pages and the index, so a search lands where the row is drawn.
final class SettingsAuditMovesTests: XCTestCase {
    private func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    private func entry(_ id: SettingsRowID) throws -> SettingsEntry {
        try XCTUnwrap(SettingsIndex.staticEntries.first { $0.id == id }, id.rawValue)
    }

    func testWhereYourMemoryLivesIsOnDevicesNotGeneral() throws {
        XCTAssertEqual(try entry(.memoryHome).section, .devices)
        XCTAssertEqual(try entry(.devicesConnection).anchor, .memoryHome,
                       "the server status row is drawn only on a server, so search lands on its card-mate")
        let devices = try source("Views/Settings/DevicesSettingsView.swift")
        let general = try source("Views/Settings/SettingsGeneralView.swift")
        XCTAssertTrue(devices.contains("MemoryHomeSetting()"))
        XCTAssertFalse(general.contains("MemoryHomeSetting()"))
        XCTAssertTrue(general.contains("SettingsInlineLink(section: .devices, row: .memoryHome"),
                      "on a server, General's Keep memory working leads to the choice")
    }

    /// D6: Devices lists the machines first, then where the memory lives, then the folded remote connector.
    func testDevicesListsTheMachinesThenWhereTheMemoryLives() throws {
        let devices = try source("Views/Settings/DevicesSettingsView.swift")
        let marks = [".settingsRow(.devicesList)", "MemoryHomeSetting()", "SettingsRow(.devicesConnection,",
                     ".settingsRow(.fromAnywhere)"]
        let body = try XCTUnwrap(devices.range(of: "struct DevicesSettingsView")).lowerBound
        let positions = try marks.map { try XCTUnwrap(devices.range(of: $0, range: body..<devices.endIndex), $0).lowerBound }
        XCTAssertEqual(positions, positions.sorted())
    }

    /// D6 (owner brief): the study room's preview leads, the hours follow, then the scenery and the character. The
    /// engine and the scheduled-plan switch moved to Intelligence.
    func testSleepLeadsWithTheStudyRoomThenTheHours() throws {
        let sleep = try source("Views/Settings/SettingsSleepView.swift")
        let marks = ["part: .preview)", "SettingsRow(.sleepRuns,", "part: .source)", "MascotSettings()"]
        let positions = try marks.map { try XCTUnwrap(sleep.range(of: $0), $0).lowerBound }
        XCTAssertEqual(positions, positions.sorted(), "preview · hours · scenery · character")
        XCTAssertFalse(sleep.contains("SettingsRow(.sleepUsePlan,"))
        XCTAssertFalse(sleep.contains("SettingsRow(.sleepEngine,"))
    }

    /// D6: Ask follows the engine; its old row lands on Intelligence's In use.
    func testAskLandsOnIntelligence() {
        XCTAssertEqual(SettingsIndex.retiredRows[.engineAsk], .settings(.intelligence, .engineChoice))
    }
}
