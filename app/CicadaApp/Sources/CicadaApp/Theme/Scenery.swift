import Foundation

typealias SkyPhase = CicadaTheme.SkyPhase

extension SkyPhase {
    var tag: String {
        switch self { case .day: "day"; case .dusk: "dusk"; case .night: "night" }
    }
    var title: String { tag.capitalized }
    static func stored(_ raw: String?) -> Self { allCases.first { $0.tag == raw } ?? .day }
}

/// Viewer preferences, independent of Home's painting and of the active bank.
enum SceneryMode: String, CaseIterable, Identifiable {
    case localWeather, sleep, choose
    static let defaultsKey = "cicada.sleep.scenerySource"
    var id: String { rawValue }
    var label: String {
        switch self { case .localWeather: "Local weather"; case .sleep: "How Sleep is doing"; case .choose: "Choose" }
    }
    static func stored(_ raw: String?) -> Self { raw.flatMap(Self.init(rawValue:)) ?? .localWeather }
}

struct ManualScenery: Equatable {
    static let timeKey = "cicada.sleep.sceneryTime"
    static let baseKey = "cicada.sleep.sceneryWeather"
    var time: SkyPhase = .day
    var base: WindowWeather = .sunny
    init(time: SkyPhase = .day, base: WindowWeather = .sunny) { self.time = time; self.base = base }
    init(timeRaw: String?, baseRaw: String?) {
        time = .stored(timeRaw)
        base = baseRaw.flatMap(WindowWeather.init(rawValue:)) ?? .sunny
    }
}

enum SkyOverlay: String, CaseIterable {
    case mist, rainbow, shootingstar
    var meaning: String { self == .mist ? "A cycle is running." : "A cycle just finished." }
    static let tags = ["mist-day", "mist-dusk", "mist-night", "rainbow-day", "rainbow-dusk", "shootingstar-night"]
}

enum ScenerySource: Equatable {
    case localWeather, sleep, fallback, chosen
    var title: String {
        switch self { case .localWeather: "local weather"; case .sleep, .fallback: "How Sleep is doing"; case .chosen: "your choice" }
    }
}

enum RoomLighting: Equatable {
    case day, dark
    func suffix(lampLit: Bool) -> String { self == .dark ? "-night-\(lampLit ? "lit" : "dark")" : "" }
}

/// Environment and Sleep moments resolve independently. No I/O, clock read, counts or changes to Sleep.
struct Scenery: Equatable {
    let base: WindowWeather
    let time: SkyPhase
    let overlay: SkyOverlay?
    let source: ScenerySource
    var weatherTag: String { "\(base.rawValue)-\(time.tag)" }
    var overlayTag: String? { overlay.map { "\($0.rawValue)-\(time.tag)" } }
    var lighting: RoomLighting { time == .night || base == .rainy ? .dark : .day }
    static let weatherTags = WindowWeather.all.flatMap { base in SkyPhase.allCases.map { "\(base.rawValue)-\($0.tag)" } }

    /// One string for the legend's current line, help and VoiceOver.
    var text: String {
        var line = "\(time.title) · \(base.title) · \(source.title)"
        if source == .fallback { line += ". Local weather unavailable." }
        if let meaning = overlay?.meaning ?? ((source == .sleep || source == .fallback) ? base.meaning : nil) {
            line += line.hasSuffix(".") ? " \(meaning)" : ". \(meaning)"
        }
        return line
    }

    static func resolve(mode: SceneryMode, clock: SkyPhase, forecast: WindowWeather?, mood: BookwormState,
                        manual: ManualScenery) -> Self {
        let time = mode == .choose ? manual.time : clock
        let base: WindowWeather
        let source: ScenerySource
        switch mode {
        case .choose: base = manual.base; source = .chosen
        case .sleep: base = windowWeather(for: mood); source = .sleep
        case .localWeather:
            base = forecast ?? windowWeather(for: mood)
            source = forecast == nil ? .fallback : .localWeather
        }
        let overlay: SkyOverlay?
        switch mood {
        case .sleeping: overlay = .mist
        case .digesting: overlay = time == .night ? .shootingstar : .rainbow
        default: overlay = nil
        }
        return Self(base: base, time: time, overlay: overlay, source: source)
    }
}

struct WeatherReading: Equatable {
    let code: Int
    let windKmh: Double
    var base: WindowWeather? {
        guard windKmh.isFinite, windKmh >= 0 else { return nil }
        if (51...67).contains(code) || (80...82).contains(code) || (95...99).contains(code) { return .rainy }
        // Snow remains cloudy until it has its own art, even in high wind.
        if [71, 73, 75, 77, 85, 86].contains(code) { return .cloudy }
        guard (0...3).contains(code) || [45, 48].contains(code) else { return nil }
        if windKmh >= 30 { return .windy }
        return code <= 1 ? .sunny : .cloudy
    }
}
