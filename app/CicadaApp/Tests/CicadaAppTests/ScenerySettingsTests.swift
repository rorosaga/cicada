import XCTest
@testable import CicadaApp

final class ScenerySettingsTests: XCTestCase {
    func testExactCopyAndSearchLandOnVisibleScenerySource() {
        XCTAssertEqual(Copy.Scenery.group, "The scenery")
        XCTAssertEqual(Copy.Scenery.disclosure, "Open-Meteo receives your time zone's city, every half hour while the study room is open; nothing else leaves your Mac.")
        for query in ["scenery", "local weather", "scenery night", "rainy"] {
            let entry = SettingsSearchLanding.topHit(query, in: SettingsIndex.staticEntries)
            XCTAssertEqual(entry?.section, .sleep, query)
            XCTAssertEqual(entry?.anchor, .scenerySource, query)
        }
        for id in [SettingsRowID.scenerySource, .sceneryTime, .sceneryWeather, .sceneryPreview] {
            XCTAssertTrue(SettingsIndex.staticIDs.contains(id))
        }
    }

    func testRoomUsesClockVisibilityAndOneTextTwinAndPreviewNeverFetches() throws {
        let root = SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp")
        let room = try String(contentsOf: root.appendingPathComponent("Views/Sleep/StudyRoom.swift"), encoding: .utf8)
        XCTAssertTrue(room.contains("clock: SceneStore.shared.phase"))
        XCTAssertTrue(room.contains("WindowVisibilityReader"))
        XCTAssertTrue(room.contains("windowVisible && !hostPaused"))
        XCTAssertTrue(room.contains("appRouter?.settingsOpen != true"))
        XCTAssertTrue(room.contains(".help(scenery.text)"))
        XCTAssertTrue(room.contains("WindowLegend(current: scenery)"))
        XCTAssertTrue(room.contains(".accessibilityLabel(\"Window, \\(scenery.text)\")"))
        let settings = try String(contentsOf: root.appendingPathComponent("Views/Settings/ScenerySettings.swift"), encoding: .utf8)
        XCTAssertFalse(settings.contains(".watch(") || settings.contains("refreshIfNeeded("))
        XCTAssertTrue(settings.contains("WeatherThumbnail("))
        XCTAssertTrue(settings.contains("SceneryRoomArt("))
        XCTAssertTrue(settings.contains(".focusable()"))
        XCTAssertTrue(settings.contains(".accessibilityLabel(voice)"))
        XCTAssertTrue(settings.contains("transaction.disablesAnimations = true"))
    }
}
