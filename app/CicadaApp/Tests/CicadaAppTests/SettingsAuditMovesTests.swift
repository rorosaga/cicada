import XCTest
@testable import CicadaApp

/// The settings audit (2026-10-22) moved three things: where your memory lives went from General to Devices, Sleep's
/// Engine card comes before the study room's look, and Ask joined the Engine card on Engines. These hold the moves to
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

    func testDevicesSaysWhereTheMemoryLivesInOneCard() throws {
        let devices = try source("Views/Settings/DevicesSettingsView.swift")
        let card = try XCTUnwrap(devices.range(of: "header: Copy.Devices.whereGroup")).lowerBound
        let choice = try XCTUnwrap(devices.range(of: "MemoryHomeSetting()", range: card..<devices.endIndex)).lowerBound
        let status = try XCTUnwrap(devices.range(of: "SettingsRow(.devicesConnection,")).lowerBound
        let next = try XCTUnwrap(devices.range(of: "header: Copy.Devices.devicesGroup")).lowerBound
        XCTAssertEqual([card, choice, status, next], [card, choice, status, next].sorted())
        XCTAssertEqual(devices.components(separatedBy: "SettingsGroupCard(header:").count - 1, 2)
    }

    func testSleepLeadsWithWhatItDoesThenTheStudyRoom() throws {
        let sleep = try source("Views/Settings/SettingsSleepView.swift")
        let marks = ["SettingsRow(.sleepRuns,", "SettingsRow(.sleepUsePlan,", "SettingsRow(.sleepEngine,",
                     "ScenerySettings(", "MascotSettings()"]
        let positions = try marks.map { try XCTUnwrap(sleep.range(of: $0), $0).lowerBound }
        XCTAssertEqual(positions, positions.sorted(), "Runs · plan switch · Engine · scenery · character")
        XCTAssertTrue(sleep.contains("SettingsInlineLink(section: .engines"), "Sleep still leads to Engines")
    }

    func testAskLivesInTheEngineCardOnEngines() throws {
        let engines = try source("Views/Settings/EnginesView.swift")
        let card = try XCTUnwrap(engines.range(of: "header: Copy.enginesChooseGroup")).lowerBound
        let chooser = try XCTUnwrap(engines.range(of: "EngineChooser(", range: card..<engines.endIndex)).lowerBound
        let ask = try XCTUnwrap(engines.range(of: "SettingsRow(.engineAsk,")).lowerBound
        let nextCard = try XCTUnwrap(engines.range(of: "SettingsGroupCard(", range: chooser..<engines.endIndex)).lowerBound
        XCTAssertTrue(card < chooser && chooser < ask && ask < nextCard, "Ask sits under the chooser, in its card")
        XCTAssertEqual(try entry(.engineAsk).section, .engines)
    }
}
