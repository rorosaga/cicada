import Foundation

/// A place on Earth, in decimal degrees (north and east positive).
struct GeoPoint: Equatable, Sendable {
    let latitude: Double
    let longitude: Double
}

/// Round-4 D4 (R-FA5) — each time zone's principal location, from the table `scripts/gen-tz-coordinates.py` builds out
/// of IANA tzdb (public domain; its `source` and `version` travel in the JSON). Loaded once; `[:]` if the bundle lost
/// the file, which only costs the painting its accuracy (the plain-clock fallback), never a crash.
enum TimeZoneCoordinates {
    static let directory = "scene"
    static let resource = "tz-coordinates"

    static let bundled: [String: GeoPoint] = load(from: .cicadaResources)

    private struct Payload: Decodable { let zones: [String: [Double]] }

    static func load(from bundle: Bundle) -> [String: GeoPoint] {
        guard let url = bundle.cicadaResource(resource, ext: "json", in: directory),
              let data = try? Data(contentsOf: url),
              let payload = try? JSONDecoder().decode(Payload.self, from: data) else { return [:] }
        return payload.zones.compactMapValues { $0.count == 2 ? GeoPoint(latitude: $0[0], longitude: $0[1]) : nil }
    }

    static func point(for identifier: String, in table: [String: GeoPoint] = bundled) -> GeoPoint? { table[identifier] }
}

/// Round-4 D4 (G144, C7) — whether it is day, dusk or night where this Mac's clock says it is, from the time zone
/// alone: NOAA's general solar-position equations (the NOAA Solar Calculator's) over the zone's tzdb point. No location
/// permission and no network: a time zone is something the Mac already knows, and a painting needs the minute, not the
/// street. Pure; `SceneClockTests`.
enum SceneClock {
    /// When the sun crosses one altitude on one day, or that it never does.
    enum Crossing: Equatable, Sendable {
        case times(rise: Date, set: Date)
        case alwaysAbove
        case alwaysBelow
    }

    struct SunTimes: Equatable, Sendable {
        /// The upper limb at the horizon with refraction (sunrise / sunset).
        let horizon: Crossing
        /// Six degrees below (civil dawn / dusk).
        let twilight: Crossing
        /// True for R-FA5's plain clock: the zone had no point.
        let estimated: Bool
    }

    static let sunriseZenith = 90.833
    static let civilZenith = 96.0
    static let fallbackSunriseHour = 7
    static let fallbackSunsetHour = 19
    static let fallbackTwilight: TimeInterval = 30 * 60
    /// R-FA6 — the store never waits longer than this before looking again.
    static let maxRecheck: TimeInterval = 3600

    static func phase(at date: Date, timeZone: TimeZone,
                      table: [String: GeoPoint] = TimeZoneCoordinates.bundled) -> CicadaTheme.SkyPhase {
        phase(at: date, sun: sun(on: date, timeZone: timeZone, table: table))
    }

    /// R-FA4 — day between the horizon crossings, dusk in civil twilight at either end, night otherwise.
    static func phase(at date: Date, sun s: SunTimes) -> CicadaTheme.SkyPhase {
        switch s.horizon {
        case .alwaysAbove: return .day
        case let .times(rise, set) where date >= rise && date < set: return .day
        default: break
        }
        switch s.twilight {
        case .alwaysAbove: return .dusk
        case let .times(dawn, dusk) where date >= dawn && date < dusk: return .dusk
        default: return .night
        }
    }

    /// R-HO1 — golden hour: the painting turns to the afternoon this long before sunset.
    static let goldenHour: TimeInterval = 2 * 3600

    /// Round-4 T-Home (C10) — which of the three paintings the clock asks for. `SkyPhase` (`phase(at:)`) stays the
    /// sky's own three steps for the Sleep room and `MeadowSky` (C7); this is the painting's.
    static func time(at date: Date, timeZone: TimeZone,
                     table: [String: GeoPoint] = TimeZoneCoordinates.bundled) -> SceneTime {
        time(at: date, sun: sun(on: date, timeZone: timeZone, table: table))
    }

    /// R-HO1 — day from sunrise; the afternoon from `afternoonStart` through evening civil twilight (the afterglow keeps
    /// the golden painting; the night one is full moonlight); night otherwise, dawn's twilight included — there is no
    /// dawn painting. A polar day never reaches an afternoon; a polar night is night; a white night (civil twilight
    /// that never ends) keeps the afternoon until local midnight, when the next day's "before sunrise" answers night.
    /// The plain clock (R-FA5) falls out of the same rule: day 07:00–17:00, afternoon 17:00–19:30.
    static func time(at date: Date, sun s: SunTimes) -> SceneTime {
        switch s.horizon {
        case .alwaysAbove: return .day
        case .alwaysBelow: return .night
        case let .times(rise, set):
            if date >= rise, date < set { return date >= afternoonStart(rise: rise, set: set) ? .afternoon : .day }
            guard date >= set else { return .night }
            switch s.twilight {
            case let .times(_, civilDusk): return date < civilDusk ? .afternoon : .night
            case .alwaysAbove: return .afternoon
            case .alwaysBelow: return .night
            }
        }
    }

    /// Two hours before sunset, never before solar noon, so a short winter day keeps a morning (R-HO1).
    static func afternoonStart(rise: Date, set: Date) -> Date {
        max(set.addingTimeInterval(-goldenHour), rise.addingTimeInterval(set.timeIntervalSince(rise) / 2))
    }

    static func sun(on date: Date, timeZone: TimeZone,
                    table: [String: GeoPoint] = TimeZoneCoordinates.bundled) -> SunTimes {
        guard let point = TimeZoneCoordinates.point(for: timeZone.identifier, in: table) else {
            return plainClock(on: date, timeZone: timeZone)
        }
        return sun(on: date, timeZone: timeZone, at: point)
    }

    /// The sun for the LOCAL calendar day `date` falls on, at `p`.
    static func sun(on date: Date, timeZone: TimeZone, at p: GeoPoint) -> SunTimes {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = timeZone
        let ymd = local.dateComponents([.year, .month, .day], from: date)
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(identifier: "UTC")!
        guard let base = utc.date(from: DateComponents(year: ymd.year, month: ymd.month, day: ymd.day)) else {
            return plainClock(on: date, timeZone: timeZone)
        }
        // Clamped so cos(latitude) never reaches 0 — at a pole the formula divides by it.
        let lat = min(max(p.latitude, -89.9), 89.9) * .pi / 180
        // R-FA5 — the UTC day whose solar noon falls on the LOCAL day asked about. A zone far from its meridian
        // (Pacific/Kiritimati is UTC+14 at 157° W) has its solar noon on another UTC date, and taking the same-dated
        // UTC day would hand it tomorrow's sunrise: night at local noon.
        for shift in [0.0, -1.0, 1.0] {
            let midnightUTC = base.addingTimeInterval(shift * 86_400)
            let solar = Solar(julianDay: midnightUTC.timeIntervalSince1970 / 86_400 + 2_440_587.5 + 0.5)
            let noonMinutes = 720 - 4 * p.longitude - solar.equationOfTime
            guard local.isDate(midnightUTC.addingTimeInterval(noonMinutes * 60), inSameDayAs: date) else { continue }
            let dec = solar.declination * .pi / 180
            func crossing(_ zenith: Double) -> Crossing {
                let arg = cos(zenith * .pi / 180) / (cos(lat) * cos(dec)) - tan(lat) * tan(dec)
                if arg > 1 { return .alwaysBelow }
                if arg < -1 { return .alwaysAbove }
                let halfDayMinutes = 4 * acos(arg) * 180 / .pi
                return .times(rise: midnightUTC.addingTimeInterval((noonMinutes - halfDayMinutes) * 60),
                              set: midnightUTC.addingTimeInterval((noonMinutes + halfDayMinutes) * 60))
            }
            return SunTimes(horizon: crossing(sunriseZenith), twilight: crossing(civilZenith), estimated: false)
        }
        return plainClock(on: date, timeZone: timeZone)
    }

    /// The next moment the phase or the painting's time can change: the soonest crossing after `date` today or tomorrow, else (a polar day or
    /// night) the next local midnight.
    static func nextBoundary(after date: Date, timeZone: TimeZone,
                             table: [String: GeoPoint] = TimeZoneCoordinates.bundled) -> Date {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = timeZone
        let tomorrow = local.date(byAdding: .day, value: 1, to: local.startOfDay(for: date)) ?? date.addingTimeInterval(86_400)
        let candidates = [date, tomorrow].flatMap { day -> [Date] in
            let s = sun(on: day, timeZone: timeZone, table: table)
            var times = [s.horizon, s.twilight].flatMap { c -> [Date] in
                if case let .times(a, b) = c { return [a, b] }
                return []
            }
            // R-HO1 — the afternoon starts on its own line, so the store crossfades to it on time.
            if case let .times(rise, set) = s.horizon { times.append(afternoonStart(rise: rise, set: set)) }
            return times
        }
        return candidates.filter { $0 > date }.min() ?? tomorrow
    }

    /// R-FA5 — a zone with no point: day 07:00–19:00 local, dusk 30 minutes either side.
    private static func plainClock(on date: Date, timeZone: TimeZone) -> SunTimes {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = timeZone
        let start = local.startOfDay(for: date)
        let rise = local.date(bySettingHour: fallbackSunriseHour, minute: 0, second: 0, of: start) ?? start
        let set = local.date(bySettingHour: fallbackSunsetHour, minute: 0, second: 0, of: start) ?? start
        return SunTimes(horizon: .times(rise: rise, set: set),
                        twilight: .times(rise: rise.addingTimeInterval(-fallbackTwilight),
                                         set: set.addingTimeInterval(fallbackTwilight)),
                        estimated: true)
    }

    /// NOAA's general solar-position terms for one Julian day (degrees and minutes).
    private struct Solar {
        let declination: Double
        let equationOfTime: Double

        init(julianDay jd: Double) {
            let t = (jd - 2_451_545) / 36_525
            let l0 = (280.46646 + t * (36_000.76983 + t * 0.0003032)).truncatingRemainder(dividingBy: 360)
            let m = 357.52911 + t * (35_999.05029 - 0.0001537 * t)
            let e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
            func r(_ d: Double) -> Double { d * .pi / 180 }
            let c = sin(r(m)) * (1.914602 - t * (0.004817 + 0.000014 * t))
                + sin(r(2 * m)) * (0.019993 - 0.000101 * t) + sin(r(3 * m)) * 0.000289
            let omega = 125.04 - 1934.136 * t
            let lambda = l0 + c - 0.00569 - 0.00478 * sin(r(omega))
            let e0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
            let eps = e0 + 0.00256 * cos(r(omega))
            declination = asin(sin(r(eps)) * sin(r(lambda))) * 180 / .pi
            let y = pow(tan(r(eps / 2)), 2)
            equationOfTime = 4 * (y * sin(2 * r(l0)) - 2 * e * sin(r(m)) + 4 * e * y * sin(r(m)) * cos(2 * r(l0))
                - 0.5 * y * y * sin(4 * r(l0)) - 1.25 * e * e * sin(2 * r(m))) * 180 / .pi
        }
    }
}

/// Round-4 D4 (R-FA6, C7) and T-Home (R-HO1) — Settings → General → Scene, per viewer, independent of Appearance:
/// Automatic follows the clock; Day, Afternoon and Night pin one painting (owner, round-4 decision 8).
enum HeroScenePreference: String, CaseIterable, Identifiable {
    case automatic, day, afternoon, night

    static let defaultsKey = "cicada.heroScene"
    var id: String { rawValue }

    var label: String {
        switch self {
        case .automatic: Copy.sceneAutomatic
        case .day: Copy.sceneDay
        case .afternoon: Copy.sceneAfternoon
        case .night: Copy.sceneNight
        }
    }

    /// Absent or unknown → Automatic.
    static func stored(_ raw: String?) -> HeroScenePreference { raw.flatMap(Self.init(rawValue:)) ?? .automatic }

    func time(clock: SceneTime) -> SceneTime {
        switch self {
        case .automatic: clock
        case .day: .day
        case .afternoon: .afternoon
        case .night: .night
        }
    }
}

/// Round-4 T-Home (C10) — the three paintings: day, the golden hour before sunset, and night. One composition in
/// three lights (ART_DIRECTION §3), so moving between them is a crossfade, never a jump.
enum SceneTime: String, CaseIterable, Sendable {
    case day, afternoon, night

    /// A surface with no Scene setting (an empty state's grass, a tiled edge) follows the theme: day under light,
    /// night under dark (ART_DIRECTION §6).
    static func forTheme(_ mode: AppColorScheme) -> SceneTime { mode == .dark ? .night : .day }

    /// The procedural sky a scene falls back to when a bundle lost its painting.
    var skyPhase: CicadaTheme.SkyPhase {
        switch self {
        case .day: .day
        case .afternoon: .dusk
        case .night: .night
        }
    }
}
