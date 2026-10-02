import SwiftUI
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
        XCTAssertTrue(room.contains(".environment(\\.scenePaused, !onScreen)"))
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

    /// Render the actual pane with isolated preferences; never touch the viewer's defaults or start a reader.
    @MainActor
    func testRenderEveryScenerySourceAndChosenSelection() throws {
        let write = ProcessInfo.processInfo.environment["CICADA_WRITE_COMPOSITES"] == "1"
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-sprite-composites/settings")
        if write { try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true) }
        let suite = "com.cicada.scenery-render.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        for scheme in AppColorScheme.allCases {
            CicadaTheme.mode = scheme
            for mode in SceneryMode.allCases {
                defaults.set(mode.rawValue, forKey: SceneryMode.defaultsKey)
                defaults.set("night", forKey: ManualScenery.timeKey)
                defaults.set("rainy", forKey: ManualScenery.baseKey)
                let pane = ScenerySettings(mood: .reading, lampLit: true)
                    .defaultAppStorage(defaults)
                    .environment(\.spriteSnapshotDate, Date(timeIntervalSince1970: 12 * 3600))
                    .environment(\.scenePaused, true)
                    .padding(24)
                    .frame(width: 640)
                    .background(CicadaTheme.background)
                let renderer = ImageRenderer(content: pane)
                renderer.scale = 2
                let image = try XCTUnwrap(renderer.cgImage, "Scenery Settings \(mode.rawValue)")
                XCTAssertEqual(image.width, 1280)
                XCTAssertGreaterThan(image.height, 200)
                if write {
                    let data = try XCTUnwrap(NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]))
                    try data.write(to: dir.appendingPathComponent("\(mode.rawValue)-\(scheme.rawValue).png"))
                }
            }
        }
    }
}
