import Foundation

// MARK: - Consumption / usage dashboard (G51)
//
// Mirrors api/models/schemas.py::{ConsumptionSummary,ConsumptionCalendar,
// ConsumptionStats,ConsumptionConnections,HarnessStats}. Every field is
// decode-tolerant (missing key → a neutral default) so an older backend, or
// a payload mid-migration, never drops the whole page.

struct ConsumptionSummary: Codable {
    var costUsd: Double = 0
    var equivCostUsd: Double = 0
    var invocations: Int = 0
    var tokens: Int = 0
    var memoryWrites: Int = 0
    var sleepRuns: Int = 0
    var agenticWrites: Int = 0
    var streakCurrent: Int = 0
    var streakBest: Int = 0
    var range: String = "30d"
    var since: String?

    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        costUsd = try c.decodeIfPresent(Double.self, forKey: .costUsd) ?? 0
        equivCostUsd = try c.decodeIfPresent(Double.self, forKey: .equivCostUsd) ?? 0
        invocations = try c.decodeIfPresent(Int.self, forKey: .invocations) ?? 0
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens) ?? 0
        memoryWrites = try c.decodeIfPresent(Int.self, forKey: .memoryWrites) ?? 0
        sleepRuns = try c.decodeIfPresent(Int.self, forKey: .sleepRuns) ?? 0
        agenticWrites = try c.decodeIfPresent(Int.self, forKey: .agenticWrites) ?? 0
        streakCurrent = try c.decodeIfPresent(Int.self, forKey: .streakCurrent) ?? 0
        streakBest = try c.decodeIfPresent(Int.self, forKey: .streakBest) ?? 0
        range = try c.decodeIfPresent(String.self, forKey: .range) ?? "30d"
        since = try c.decodeIfPresent(String.self, forKey: .since)
    }
}

struct CalendarDay: Codable, Identifiable {
    let date: String
    let memoryWrites: Int
    let events: Int
    let tokens: Int
    let costUsd: Double
    let equivCostUsd: Double
    let level: Int
    var id: String { date }

    enum CodingKeys: String, CodingKey { case date, memoryWrites, events, tokens, costUsd, equivCostUsd, level }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        memoryWrites = try c.decodeIfPresent(Int.self, forKey: .memoryWrites) ?? 0
        events = try c.decodeIfPresent(Int.self, forKey: .events) ?? 0
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens) ?? 0
        costUsd = try c.decodeIfPresent(Double.self, forKey: .costUsd) ?? 0
        equivCostUsd = try c.decodeIfPresent(Double.self, forKey: .equivCostUsd) ?? 0
        level = try c.decodeIfPresent(Int.self, forKey: .level) ?? 0
    }
    /// Projection consumed by `CalendarLayout` (Task 7).
    var cell: CalendarCell { CalendarCell(date: date, level: level, memoryWrites: memoryWrites, events: events, tokens: tokens) }
}

struct ConsumptionCalendar: Codable {
    let days: [CalendarDay]
    let weeks: Int
}

/// One row of a by-model / by-stage / by-connection / by-bank table. The
/// backend sends loose dicts; the first string-valued key is the row name.
struct StatsRow: Codable, Identifiable {
    let name: String
    let invocations: Int
    let inputTokens: Int
    let outputTokens: Int
    let cacheReadTokens: Int
    let cacheWriteTokens: Int
    let tokens: Int
    let costUsd: Double?
    let equivCostUsd: Double?
    var id: String { name }

    private struct Key: CodingKey {
        var stringValue: String; var intValue: Int? { nil }
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { nil }
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Key.self)
        func int(_ k: String) -> Int { (try? c.decodeIfPresent(Int.self, forKey: Key(stringValue: k)!)) ?? 0 }
        func dbl(_ k: String) -> Double? { try? c.decodeIfPresent(Double.self, forKey: Key(stringValue: k)!) }
        name = ["model", "stage", "connection", "bank"].lazy
            .compactMap { try? c.decodeIfPresent(String.self, forKey: Key(stringValue: $0)!) }.first ?? "unknown"
        invocations = int("invocations"); inputTokens = int("inputTokens"); outputTokens = int("outputTokens")
        cacheReadTokens = int("cacheReadTokens"); cacheWriteTokens = int("cacheWriteTokens"); tokens = int("tokens")
        costUsd = dbl("costUsd"); equivCostUsd = dbl("equivCostUsd")
    }
}

struct SeriesPoint: Codable, Identifiable {
    let date: String
    let tokens: Int
    let costUsd: Double
    let equivCostUsd: Double
    let events: Int
    var id: String { date }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens) ?? 0
        costUsd = try c.decodeIfPresent(Double.self, forKey: .costUsd) ?? 0
        equivCostUsd = try c.decodeIfPresent(Double.self, forKey: .equivCostUsd) ?? 0
        events = try c.decodeIfPresent(Int.self, forKey: .events) ?? 0
    }
}

struct ConsumptionStats: Codable {
    let byModel: [StatsRow]
    let byStage: [StatsRow]
    let byConnection: [StatsRow]
    let byBank: [StatsRow]
    let hourHistogram: [Int]
    let peakDay: [String: LooseValue]?
    let longestSleepRun: [String: LooseValue]?
    let favoriteModel: String?
    let lifetimeTokens: Int
    let firstEvent: String?
    let series: [SeriesPoint]
    let range: String

    enum CodingKeys: String, CodingKey {
        case byModel, byStage, byConnection, byBank, hourHistogram, peakDay, longestSleepRun, favoriteModel, lifetimeTokens, firstEvent, series, range
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        byModel = try c.decodeIfPresent([StatsRow].self, forKey: .byModel) ?? []
        byStage = try c.decodeIfPresent([StatsRow].self, forKey: .byStage) ?? []
        byConnection = try c.decodeIfPresent([StatsRow].self, forKey: .byConnection) ?? []
        byBank = try c.decodeIfPresent([StatsRow].self, forKey: .byBank) ?? []
        hourHistogram = try c.decodeIfPresent([Int].self, forKey: .hourHistogram) ?? Array(repeating: 0, count: 24)
        peakDay = try c.decodeIfPresent([String: LooseValue].self, forKey: .peakDay)
        longestSleepRun = try c.decodeIfPresent([String: LooseValue].self, forKey: .longestSleepRun)
        favoriteModel = try c.decodeIfPresent(String.self, forKey: .favoriteModel)
        lifetimeTokens = try c.decodeIfPresent(Int.self, forKey: .lifetimeTokens) ?? 0
        firstEvent = try c.decodeIfPresent(String.self, forKey: .firstEvent)
        series = try c.decodeIfPresent([SeriesPoint].self, forKey: .series) ?? []
        range = try c.decodeIfPresent(String.self, forKey: .range) ?? "30d"
    }
}

/// String | number | null — for the small free-form dicts (peakDay, longestSleepRun, harness).
enum LooseValue: Codable, Hashable {
    case string(String), number(Double), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let d = try? c.decode(Double.self) { self = .number(d) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else { self = .null }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self { case .string(let s): try c.encode(s); case .number(let d): try c.encode(d); case .null: try c.encodeNil() }
    }
    var text: String { switch self { case .string(let s): s; case .number(let d): d == d.rounded() ? "\(Int(d))" : "\(d)"; case .null: "—" } }
    var number: Double? { if case .number(let d) = self { d } else { nil } }
}

struct ConnectionConsumption: Codable, Identifiable {
    let id: String
    let label: String
    let billing: String
    let connected: Bool
    let priceUsdMonth: Double?
    let costUsd: Double?
    let equivCostUsd: Double?
    let invocations: Int
    let tokens: Int
    let throttleEvents: Int
    let byModel: [StatsRow]

    enum CodingKeys: String, CodingKey { case id, label, billing, connected, priceUsdMonth, costUsd, equivCostUsd, invocations, tokens, throttleEvents, byModel }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        billing = try c.decodeIfPresent(String.self, forKey: .billing) ?? "usage"
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        priceUsdMonth = try c.decodeIfPresent(Double.self, forKey: .priceUsdMonth)
        costUsd = try c.decodeIfPresent(Double.self, forKey: .costUsd)
        equivCostUsd = try c.decodeIfPresent(Double.self, forKey: .equivCostUsd)
        invocations = try c.decodeIfPresent(Int.self, forKey: .invocations) ?? 0
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens) ?? 0
        throttleEvents = try c.decodeIfPresent(Int.self, forKey: .throttleEvents) ?? 0
        byModel = try c.decodeIfPresent([StatsRow].self, forKey: .byModel) ?? []
    }
}

struct ConsumptionConnections: Codable {
    let connections: [ConnectionConsumption]
    let range: String
}

struct HarnessStats: Codable {
    let claudeCode: [String: LooseValueTree]?
    let codex: [String: LooseValueTree]?
}

/// Recursive loose JSON for the harness panel (arrays of dicts, nested dicts).
indirect enum LooseValueTree: Codable {
    case value(LooseValue), array([LooseValueTree]), object([String: LooseValueTree])
    init(from decoder: Decoder) throws {
        if let o = try? [String: LooseValueTree](from: decoder) { self = .object(o) }
        else if let a = try? [LooseValueTree](from: decoder) { self = .array(a) }
        else { self = .value(try LooseValue(from: decoder)) }
    }
    func encode(to encoder: Encoder) throws {
        switch self {
        case .value(let v): try v.encode(to: encoder)
        case .array(let a): try a.encode(to: encoder)
        case .object(let o): try o.encode(to: encoder)
        }
    }
    subscript(_ key: String) -> LooseValueTree? { if case .object(let o) = self { o[key] } else { nil } }
    var array: [LooseValueTree] { if case .array(let a) = self { a } else { [] } }
    var value: LooseValue? { if case .value(let v) = self { v } else { nil } }
}

/// The Store's `consumption` sync domain (G51). The backend serves five
/// separate endpoints (`/consumption/summary|calendar|stats|connections|harness`),
/// but only one of each is needed for the dashboard's default view (range
/// "month", 53-week calendar) — `APIClient.fetchConsumption(etag:)` fans out
/// to all five and folds them into this one bundle so the whole page hydrates
/// from a single disk snapshot and reconciles off a single SSE-driven refresh.
/// A non-"month" range is fetched directly by `UsageViewModel` and never
/// touches this bundle or the on-disk cache (see `loadRange()`).
struct ConsumptionBundle: Codable {
    let summary: ConsumptionSummary
    let calendar: ConsumptionCalendar
    let stats: ConsumptionStats
    let connections: ConsumptionConnections
    let harness: HarnessStats
}
