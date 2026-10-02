import XCTest
@testable import CicadaApp

final class SceneryTests: XCTestCase {
    func testMoodBasesAndClockAreIndependent() {
        let bases: [WindowWeather] = [.curtains, .cloudy, .sunny, .sunny, .sunny, .windy, .rainy, .cloudy]
        let moods: [BookwormState] = [.awake, .reading, .sleeping(stage: 1), .digesting, .happy, .hungry, .error, .curious(count: 1)]
        for (mood, base) in zip(moods, bases) {
            for phase in SkyPhase.allCases {
                let s = Scenery.resolve(mode: .sleep, clock: phase, forecast: nil, mood: mood, manual: .init())
                XCTAssertEqual(s.base, base)
                XCTAssertEqual(s.time, phase)
                XCTAssertEqual(s.source, .sleep)
                XCTAssertEqual(s.lighting, phase == .night || base == .rainy ? .dark : .day)
            }
        }
    }

    func testOverlaysFollowMoodInEveryModeWeatherAndTime() {
        for mode in SceneryMode.allCases { for phase in SkyPhase.allCases { for base in WindowWeather.all {
            for mood in BookwormArt.states {
                let s = Scenery.resolve(mode: mode, clock: phase, forecast: base, mood: mood,
                                        manual: .init(time: phase, base: base))
                let expected: SkyOverlay? = mood.caseName == "sleeping" ? .mist
                    : mood.caseName == "digesting" ? (phase == .night ? .shootingstar : .rainbow) : nil
                XCTAssertEqual(s.overlay, expected)
                XCTAssertEqual(s.overlayTag, expected.map { "\($0.rawValue)-\(s.time.tag)" })
                if let expected {
                    XCTAssertTrue(s.text.contains(expected.meaning))
                    XCTAssertFalse(s.text.contains("Caught up. Nothing waiting."), "running/completion never claims an empty queue")
                }
            }
        } } }
    }

    func testManualIgnoresForecastAndClockAndLocalFallsBack() {
        let manual = ManualScenery(time: .dusk, base: .curtains)
        let chosen = Scenery.resolve(mode: .choose, clock: .night, forecast: .rainy, mood: .error, manual: manual)
        XCTAssertEqual(chosen, Scenery(base: .curtains, time: .dusk, overlay: nil, source: .chosen))
        let local = Scenery.resolve(mode: .localWeather, clock: .night, forecast: .rainy, mood: .happy, manual: manual)
        XCTAssertEqual(local.source, .localWeather)
        XCTAssertEqual(local.base, .rainy)
        XCTAssertEqual(local.text, "Night · Rainy · local weather")
        let fallback = Scenery.resolve(mode: .localWeather, clock: .day, forecast: nil, mood: .hungry, manual: manual)
        XCTAssertEqual(fallback.source, .fallback)
        XCTAssertEqual(fallback.base, .windy)
        XCTAssertEqual(fallback.text, "Day · Windy · How Sleep is doing. Local weather unavailable. Overdue: it's been a while.")
        XCTAssertEqual(Scenery.resolve(mode: .choose, clock: .day, forecast: nil, mood: .digesting,
                                      manual: .init(time: .night, base: .cloudy)).text,
                       "Night · Cloudy · your choice. A cycle just finished.")
    }

    func testForecastMappingPrecipitationWinsOverWindAndUnknownFallsBack() {
        for code in [0, 1] { XCTAssertEqual(WeatherReading(code: code, windKmh: 29.9).base, .sunny) }
        for code in [2, 3, 45, 48, 71, 73, 75, 77, 85, 86] {
            XCTAssertEqual(WeatherReading(code: code, windKmh: 0).base, .cloudy)
        }
        for code in [0, 1, 2, 3, 45, 48] { XCTAssertEqual(WeatherReading(code: code, windKmh: 30).base, .windy) }
        for code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99] {
            XCTAssertEqual(WeatherReading(code: code, windKmh: 100).base, .rainy)
        }
        for code in [71, 73, 75, 77, 85, 86] { XCTAssertEqual(WeatherReading(code: code, windKmh: 100).base, .cloudy) }
        XCTAssertNil(WeatherReading(code: -1, windKmh: 0).base)
        XCTAssertNil(WeatherReading(code: 123, windKmh: 30).base)
        XCTAssertNil(WeatherReading(code: 0, windKmh: .nan).base)
        XCTAssertNil(WeatherReading(code: 0, windKmh: -1).base)
    }

    func testStoredPreferencesDefaultSafelyAndKeepSeparateViewerKeys() {
        XCTAssertEqual(SceneryMode.stored(nil), .localWeather)
        XCTAssertEqual(SceneryMode.stored("retired"), .localWeather)
        XCTAssertEqual(ManualScenery(timeRaw: "bad", baseRaw: "bad"), .init())
        XCTAssertEqual(ManualScenery(timeRaw: "night", baseRaw: "rainy"), .init(time: .night, base: .rainy))
        XCTAssertEqual(Set([SceneryMode.defaultsKey, ManualScenery.timeKey, ManualScenery.baseKey]).count, 3)
        XCTAssertEqual(SceneryMode.allCases.map(\.label), ["Local weather", "How Sleep is doing", "Choose"])
    }
}
