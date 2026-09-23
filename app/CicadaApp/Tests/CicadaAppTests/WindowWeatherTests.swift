import XCTest
@testable import CicadaApp

/// Track Z R-Z11 — the window is weather, and the weather is state: total
/// over the mood, reading nothing else, listed once, with a legend twin.
final class WindowWeatherTests: XCTestCase {

    func test_everyMoodHasOneWeather_andNoQuantityMovesIt() {
        XCTAssertEqual(windowWeather(for: .awake), .curtains)
        XCTAssertEqual(windowWeather(for: .digesting), .dawn)
        XCTAssertEqual(windowWeather(for: .happy), .clear)
        XCTAssertEqual(windowWeather(for: .reading), .fair)
        XCTAssertEqual(windowWeather(for: .hungry), .overcast)
        XCTAssertEqual(windowWeather(for: .error), .storm)
        for stage in 1...5 { XCTAssertEqual(windowWeather(for: .sleeping(stage: stage)), .night, "the moon never travels") }
        XCTAssertEqual(windowWeather(for: .curious(count: 1)), windowWeather(for: .curious(count: 99)))
    }

    func test_theWeathersAreListedOnce_withDistinctWords() {
        XCTAssertEqual(WindowWeather.all, WindowWeather.allCases)
        XCTAssertEqual(Set(WindowWeather.all.map(\.title)).count, 7)
        XCTAssertEqual(Set(WindowWeather.all.map(\.meaning)).count, 7)
        for weather in WindowWeather.all {
            XCTAssertFalse(weather.meaning.contains("!") || weather.meaning.contains("%"), weather.meaning)
        }
    }

    /// "No weather driven by a count or the clock" (§7.3) — by grep.
    func test_theWeatherReadsNoClock() throws {
        let file = try SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "WindowWeather.swift" }!
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(text.contains("Date("))
        XCTAssertFalse(text.contains("Calendar"))
    }

    /// P16 — the legend is the ONE list of meanings; the `?` popover points at
    /// it and copies none of it.
    func test_howSleepWorksPointsAtTheLegendWithoutCopyingIt() throws {
        let file = try SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "HowSleepWorks.swift" }!
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("Copy.windowLegendPointer"))
        for weather in WindowWeather.all { XCTAssertFalse(text.contains(weather.meaning), weather.meaning) }
    }
}
