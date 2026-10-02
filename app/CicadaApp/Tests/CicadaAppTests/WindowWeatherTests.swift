import XCTest
@testable import CicadaApp

/// Track Z R-Z11 — the fallback weather is state: total
/// over the mood, reading nothing else, listed once, with a legend twin.
final class WindowWeatherTests: XCTestCase {

    func test_everyMoodHasOneWeather_andNoQuantityMovesIt() {
        XCTAssertEqual(windowWeather(for: .awake), .curtains)
        XCTAssertEqual(windowWeather(for: .digesting), .sunny)
        XCTAssertEqual(windowWeather(for: .happy), .sunny)
        XCTAssertEqual(windowWeather(for: .reading), .cloudy)
        XCTAssertEqual(windowWeather(for: .hungry), .windy)
        XCTAssertEqual(windowWeather(for: .error), .rainy)
        for stage in 1...5 { XCTAssertEqual(windowWeather(for: .sleeping(stage: stage)), .sunny, "running does not choose the hour") }
        XCTAssertEqual(windowWeather(for: .curious(count: 1)), windowWeather(for: .curious(count: 99)))
    }

    func test_theWeathersAreListedOnce_withDistinctWords() {
        XCTAssertEqual(WindowWeather.all, WindowWeather.allCases)
        XCTAssertEqual(WindowWeather.all.map(\.title), ["Sunny", "Cloudy", "Windy", "Rainy", "Curtains drawn"])
        XCTAssertEqual(Set(WindowWeather.all.map(\.title)).count, 5)
        XCTAssertEqual(Set(WindowWeather.all.map(\.meaning)).count, 5)
        for weather in WindowWeather.all {
            XCTAssertFalse(weather.meaning.contains("!") || weather.meaning.contains("%"), weather.meaning)
        }
    }

    /// "The mood fallback does not read a clock" (§7.3) — by grep.
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
