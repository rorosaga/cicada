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

    func testThePreferenceOverridesTheClock() {
        XCTAssertEqual(HeroScenePreference.stored(nil), .automatic)
        XCTAssertEqual(HeroScenePreference.stored("sunset"), .automatic, "an unknown value is Automatic")
        XCTAssertEqual(HeroScenePreference.stored("night"), .night)
        XCTAssertEqual(HeroScenePreference.automatic.scene(clock: .dusk), .dusk)
        XCTAssertEqual(HeroScenePreference.day.scene(clock: .night), .day)
        XCTAssertEqual(HeroScenePreference.night.scene(clock: .day), .night)
        XCTAssertEqual(HeroScenePreference.defaultsKey, "cicada.heroScene")
    }

    /// R-FA4 — day paints hero-day; dusk and night its -dark sibling, whatever the theme.
    func testTheHeroPicksItsPaintingByTheScene() {
        XCTAssertEqual(MeadowArt.fileName(for: .heroDay, mode: MeadowArt.heroMode(for: .day)), "hero-day")
        XCTAssertEqual(MeadowArt.fileName(for: .heroDay, mode: MeadowArt.heroMode(for: .dusk)), "hero-day-dark")
        XCTAssertEqual(MeadowArt.fileName(for: .heroDay, mode: MeadowArt.heroMode(for: .night)), "hero-day-dark")
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

    /// The hero follows the scene, never the theme (source check, the HomeBandLayoutTests precedent).
    func testTheHeroViewsDoNotReadTheThemeForThePainting() throws {
        let files = try ThemeTokenTests.swiftSources()
        for suffix in ["Views/Meadow/HomeHeroBand.swift", "Views/Meadow/WelcomeHero.swift"] {
            let text = try String(contentsOf: XCTUnwrap(files.first { $0.path.hasSuffix(suffix) }), encoding: .utf8)
            XCTAssertFalse(text.contains("mode: CicadaTheme.mode"), suffix)
            XCTAssertTrue(text.contains("MeadowArt.heroMode(for:"), suffix)
        }
    }
}
