import XCTest
@testable import CicadaApp

/// Round-4 D4 (G144) — the Home painting's clock: NOAA's sun over each time zone's tzdb point, no location.
final class SceneClockTests: XCTestCase {
    private func date(_ y: Int, _ m: Int, _ d: Int, _ h: Int, _ min: Int, _ zone: String) -> Date {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: zone)!
        return c.date(from: DateComponents(year: y, month: m, day: d, hour: h, minute: min))!
    }

    private func assertNear(_ actual: Date?, _ expected: Date, file: StaticString = #filePath, line: UInt = #line) {
        guard let actual else { return XCTFail("no time", file: file, line: line) }
        XCTAssertLessThanOrEqual(abs(actual.timeIntervalSince(expected)), 5 * 60, "\(actual) vs \(expected)",
                                 file: file, line: line)
    }

    private func riseSet(_ zone: String, _ y: Int, _ m: Int, _ d: Int) throws -> (Date, Date) {
        let tz = try XCTUnwrap(TimeZone(identifier: zone))
        let sun = SceneClock.sun(on: date(y, m, d, 12, 0, zone), timeZone: tz)
        guard case let .times(rise, set) = sun.horizon else { throw XCTSkip("no crossing") }
        XCTAssertFalse(sun.estimated, "\(zone) has a tzdb point")
        return (rise, set)
    }

    func testKnownSunrisesAndSunsetsWithinFiveMinutes() throws {
        let ny = try riseSet("America/New_York", 2026, 6, 21)
        assertNear(ny.0, date(2026, 6, 21, 5, 25, "America/New_York"))
        assertNear(ny.1, date(2026, 6, 21, 20, 31, "America/New_York"))
        let tokyo = try riseSet("Asia/Tokyo", 2026, 6, 21)
        assertNear(tokyo.0, date(2026, 6, 21, 4, 25, "Asia/Tokyo"))
        assertNear(tokyo.1, date(2026, 6, 21, 19, 0, "Asia/Tokyo"))
        let madrid = try riseSet("Europe/Madrid", 2026, 12, 21)
        assertNear(madrid.0, date(2026, 12, 21, 8, 34, "Europe/Madrid"))
        assertNear(madrid.1, date(2026, 12, 21, 17, 51, "Europe/Madrid"))
    }

    func testThePhasesOfOneDay() {
        let ny = TimeZone(identifier: "America/New_York")!
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 12, 0, "America/New_York"), timeZone: ny), .day)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 20, 50, "America/New_York"), timeZone: ny), .dusk)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 23, 0, "America/New_York"), timeZone: ny), .night)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 5, 5, "America/New_York"), timeZone: ny), .dusk,
                       "dawn's twilight is the dusk phase — SkyPhase has no dawn (R-FA4)")
    }

    // MARK: The afternoon (round-4 T-Home, R-HO1)

    func testTheAfternoonIsTheLastTwoHoursOfSunThroughCivilDusk() {
        let ny = TimeZone(identifier: "America/New_York")!
        func at(_ h: Int, _ m: Int) -> SceneTime {
            SceneClock.time(at: date(2026, 6, 21, h, m, "America/New_York"), timeZone: ny)
        }
        // Sunset 20:31, so golden hour starts ~18:31; evening civil twilight ends ~21:04.
        XCTAssertEqual(at(12, 0), .day)
        XCTAssertEqual(at(18, 15), .day)
        XCTAssertEqual(at(18, 45), .afternoon)
        XCTAssertEqual(at(20, 50), .afternoon, "the afterglow keeps the golden painting until civil dusk")
        XCTAssertEqual(at(21, 30), .night)
        XCTAssertEqual(at(5, 5), .night, "dawn's twilight is night: there is no dawn painting")
        XCTAssertEqual(at(6, 0), .day)
    }

    /// R-HO1 — never before solar noon, so a short winter day keeps its morning.
    func testAShortDayKeepsItsMorning() {
        let rise = Date(timeIntervalSince1970: 1_800_000_000)
        let set = rise.addingTimeInterval(2 * 3600)
        let sun = SceneClock.SunTimes(horizon: .times(rise: rise, set: set),
                                      twilight: .times(rise: rise.addingTimeInterval(-1800),
                                                       set: set.addingTimeInterval(1800)),
                                      estimated: false)
        XCTAssertEqual(SceneClock.afternoonStart(rise: rise, set: set), rise.addingTimeInterval(3600))
        XCTAssertEqual(SceneClock.time(at: rise.addingTimeInterval(1800), sun: sun), .day)
        XCTAssertEqual(SceneClock.time(at: rise.addingTimeInterval(4000), sun: sun), .afternoon)
        XCTAssertEqual(SceneClock.time(at: set.addingTimeInterval(1000), sun: sun), .afternoon)
        XCTAssertEqual(SceneClock.time(at: set.addingTimeInterval(2000), sun: sun), .night)
    }

    /// R-HO1 — a white night (the sun sets, civil twilight never ends) keeps the afterglow until local midnight.
    func testAWhiteNightKeepsTheAfterglow() {
        let rise = Date(timeIntervalSince1970: 1_800_000_000)
        let set = rise.addingTimeInterval(20 * 3600)
        let sun = SceneClock.SunTimes(horizon: .times(rise: rise, set: set), twilight: .alwaysAbove, estimated: false)
        XCTAssertEqual(SceneClock.time(at: set.addingTimeInterval(1800), sun: sun), .afternoon)
        XCTAssertEqual(SceneClock.time(at: rise.addingTimeInterval(-600), sun: sun), .night)
    }

    func testPolarDayHasNoAfternoonAndPolarNightIsNight() {
        let svalbard = TimeZone(identifier: "Arctic/Longyearbyen")!
        XCTAssertEqual(SceneClock.time(at: date(2026, 6, 21, 18, 0, "Arctic/Longyearbyen"), timeZone: svalbard), .day)
        XCTAssertEqual(SceneClock.time(at: date(2026, 12, 21, 12, 0, "Arctic/Longyearbyen"), timeZone: svalbard), .night)
    }

    func testAZoneWithNoPointUsesThePlainClock() {
        let ny = TimeZone(identifier: "America/New_York")!
        func at(_ h: Int, _ m: Int) -> SceneTime {
            SceneClock.time(at: date(2026, 6, 21, h, m, "America/New_York"), timeZone: ny, table: [:])
        }
        XCTAssertEqual(at(16, 30), .day)
        XCTAssertEqual(at(17, 30), .afternoon)
        XCTAssertEqual(at(19, 45), .night)
    }

    func testTheNextLookIncludesTheStartOfTheAfternoon() {
        let ny = TimeZone(identifier: "America/New_York")!
        let next = SceneClock.nextBoundary(after: date(2026, 6, 21, 17, 0, "America/New_York"), timeZone: ny)
        XCTAssertLessThanOrEqual(abs(next.timeIntervalSince(date(2026, 6, 21, 18, 31, "America/New_York"))), 5 * 60)
    }

    @MainActor
    func testTheStoreCarriesTheClocksSceneAndThePowerState() {
        let ny = TimeZone(identifier: "America/New_York")!
        let seven = date(2026, 6, 21, 19, 0, "America/New_York")
        let store = SceneStore(now: { seven }, timeZone: { ny }, lowPower: { true })
        XCTAssertEqual(store.time, .afternoon)
        XCTAssertEqual(store.phase, .day, "C7's phase is unchanged: to the sky the afternoon is still day")
        XCTAssertTrue(store.lowPower)
    }

    func testThePreferenceOverridesTheClock() {
        XCTAssertEqual(HeroScenePreference.stored(nil), .automatic)
        XCTAssertEqual(HeroScenePreference.stored("sunset"), .automatic, "an unknown value is Automatic")
        XCTAssertEqual(HeroScenePreference.stored("night"), .night)
        XCTAssertEqual(HeroScenePreference.stored("afternoon"), .afternoon)
        XCTAssertEqual(HeroScenePreference.automatic.time(clock: .afternoon), .afternoon)
        XCTAssertEqual(HeroScenePreference.day.time(clock: .night), .day)
        XCTAssertEqual(HeroScenePreference.afternoon.time(clock: .day), .afternoon)
        XCTAssertEqual(HeroScenePreference.night.time(clock: .day), .night)
        XCTAssertEqual(HeroScenePreference.defaultsKey, "cicada.heroScene")
        XCTAssertEqual(HeroScenePreference.allCases.map(\.label), ["Automatic", "Day", "Afternoon", "Night"],
                       "F-10's words (round-4 decision 8)")
    }

    func testASurfaceWithNoSceneFollowsTheTheme() {
        XCTAssertEqual(SceneTime.forTheme(.light), .day)
        XCTAssertEqual(SceneTime.forTheme(.dark), .night)
    }

    /// R-HO8 — one painting per scene; the afternoon has its own file now.
    func testTheHeroPicksItsPaintingByTheScene() {
        XCTAssertEqual(MeadowArt.fileName(for: .hero, time: .day), "hero-day")
        XCTAssertEqual(MeadowArt.fileName(for: .hero, time: .afternoon), "hero-afternoon")
        XCTAssertEqual(MeadowArt.fileName(for: .hero, time: .night), "hero-night")
    }

    func testPolarDayAndNightFallBackSanely() {
        let svalbard = TimeZone(identifier: "Arctic/Longyearbyen")!
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 0, 30, "Arctic/Longyearbyen"), timeZone: svalbard), .day)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 12, 21, 12, 0, "Arctic/Longyearbyen"), timeZone: svalbard), .night)
        let mcmurdo = TimeZone(identifier: "Antarctica/McMurdo")!
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 12, 0, "Antarctica/McMurdo"), timeZone: mcmurdo), .night)
        let now = date(2026, 6, 21, 12, 0, "Arctic/Longyearbyen")
        let next = SceneClock.nextBoundary(after: now, timeZone: svalbard)
        XCTAssertGreaterThan(next, now)
        XCTAssertLessThanOrEqual(next.timeIntervalSince(now), 24 * 3600, "with no crossing, the next local midnight")
    }

    /// R-FA5 — a zone far from its meridian gets ITS day's sun, not the next day's (Kiritimati is UTC+14 at 157° W).
    func testAZoneAcrossTheDateLineGetsItsOwnDay() throws {
        let zone = "Pacific/Kiritimati"
        let tz = try XCTUnwrap(TimeZone(identifier: zone))
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 12, 0, zone), timeZone: tz), .day)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 3, 0, zone), timeZone: tz), .night)
        let (rise, _) = try riseSet(zone, 2026, 6, 21)
        var c = Calendar(identifier: .gregorian)
        c.timeZone = tz
        XCTAssertTrue(c.isDate(rise, inSameDayAs: date(2026, 6, 21, 12, 0, zone)), "the sunrise of the day asked about")
    }

    /// Every zone this Mac can be set to is day at 13:00 and night at 01:00 on the September equinox — no zone is
    /// polar then. Before R-FA5's day choice, 8 Pacific zones read night at 13:00.
    func testEveryZoneIsDayAtOneAndNightAtOneOnTheEquinox() {
        var wrong: [String] = []
        for zone in TimeZone.knownTimeZoneIdentifiers {
            guard let tz = TimeZone(identifier: zone) else { continue }
            let afternoon = SceneClock.phase(at: date(2026, 9, 23, 13, 0, zone), timeZone: tz)
            let night = SceneClock.phase(at: date(2026, 9, 23, 1, 0, zone), timeZone: tz)
            if afternoon != .day || night != .night { wrong.append("\(zone): \(afternoon)/\(night)") }
        }
        XCTAssertEqual(wrong, [])
    }

    /// At a pole the formula divides by cos(latitude); the clamp keeps it an answer, never NaN.
    func testAPointAtThePoleStillAnswers() {
        let utc = TimeZone(identifier: "UTC")!
        let pole = GeoPoint(latitude: 90, longitude: 0)
        XCTAssertEqual(SceneClock.sun(on: date(2026, 6, 21, 12, 0, "UTC"), timeZone: utc, at: pole).horizon, .alwaysAbove)
        XCTAssertEqual(SceneClock.sun(on: date(2026, 12, 21, 12, 0, "UTC"), timeZone: utc, at: pole).horizon, .alwaysBelow)
    }

    func testAZoneWithNoPointKeepsAPlainClock() {
        let gmt = TimeZone(identifier: "GMT")!
        XCTAssertTrue(SceneClock.sun(on: date(2026, 9, 24, 12, 0, "GMT"), timeZone: gmt).estimated)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 9, 24, 12, 0, "GMT"), timeZone: gmt), .day)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 9, 24, 6, 45, "GMT"), timeZone: gmt), .dusk)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 9, 24, 2, 0, "GMT"), timeZone: gmt), .night)
    }

    /// R-FA5 — the bundled table covers every zone this Mac can be set to, but GMT/UTC.
    func testTheBundledTableCoversEveryKnownZone() {
        XCTAssertGreaterThan(TimeZoneCoordinates.bundled.count, 400)
        let missing = TimeZone.knownTimeZoneIdentifiers.filter {
            !["GMT", "UTC"].contains($0) && TimeZoneCoordinates.point(for: $0) == nil
        }
        XCTAssertEqual(missing, [], "re-run scripts/gen-tz-coordinates.py")
    }

    /// R-FA6 — the store looks again at the next boundary, or within the hour.
    @MainActor
    func testTheStoreRechecksAtTheNextBoundaryOrWithinTheHour() {
        let ny = TimeZone(identifier: "America/New_York")!
        let justBeforeSunset = date(2026, 6, 21, 20, 20, "America/New_York")
        let store = SceneStore(now: { justBeforeSunset }, timeZone: { ny })
        XCTAssertEqual(store.phase, .day)
        XCTAssertLessThan(store.delayUntilNextCheck(), 20 * 60)
        let noon = date(2026, 6, 21, 12, 0, "America/New_York")
        XCTAssertEqual(SceneStore(now: { noon }, timeZone: { ny }).delayUntilNextCheck(), SceneClock.maxRecheck)
    }

    /// The hero follows the clock and the Scene setting, never the theme (G144) — one door, `PaintedScene`.
    func testTheHeroViewsDoNotReadTheThemeForThePainting() throws {
        let files = try ThemeTokenTests.swiftSources()
        func text(_ suffix: String) throws -> String {
            try String(contentsOf: XCTUnwrap(files.first { $0.path.hasSuffix(suffix) }, suffix), encoding: .utf8)
        }
        XCTAssertTrue(try text("Views/Meadow/HomeHeroBand.swift").contains("PaintedScene(.hero(band:"))
        XCTAssertTrue(try text("Views/Meadow/WelcomeHero.swift").contains("PaintedScene(.fullBleed"))
        for suffix in ["Views/Meadow/PaintedScene.swift", "Views/Meadow/SceneFraming.swift",
                       "Views/Meadow/SceneMotion.swift"] {
            XCTAssertFalse(try text(suffix).contains("CicadaTheme.mode"), suffix)
        }
    }
}
