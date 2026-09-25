import Foundation

// MARK: - Contributors calendar + read/write stats (G124)
//
// Mirrors api/models/schemas.py::{ContributorCalendar,TopEntities,
// TopEntityWrite,TopEntityRead}. Every field is decode-tolerant (missing key
// → a neutral default) so an older backend never blanks the Contributors
// drill-down or the Advanced section — the same rule `Consumption.swift`
// follows for its siblings.

/// `GET /contributors/calendar?author=` (G124 R14): `/consumption/calendar`'s
/// shape for one `Cicada-Author`. `days` are `CalendarDay`s with only
/// `memoryWrites`/`level` populated — events, tokens and cost stay 0, which
/// is what lets the one `HeatmapView` render both calendars unchanged.
struct ContributorCalendar: Codable {
    let author: String
    let days: [CalendarDay]
    let weeks: Int
    enum CodingKeys: String, CodingKey { case author, days, weeks }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        author = try c.decodeIfPresent(String.self, forKey: .author) ?? ""
        days = (try? c.decodeIfPresent([CalendarDay].self, forKey: .days)) ?? []
        weeks = try c.decodeIfPresent(Int.self, forKey: .weeks) ?? 53
    }
}

/// One most-written row: an entity page and how many of the scanned commits
/// touched it. `lastWritten` is an ISO date.
struct TopEntityWrite: Codable, Identifiable, Equatable {
    let entityId: String; let commits: Int; let lastWritten: String
    var id: String { entityId }
    enum CodingKeys: String, CodingKey { case entityId, commits, lastWritten }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decode(String.self, forKey: .entityId)
        commits = try c.decodeIfPresent(Int.self, forKey: .commits) ?? 0
        lastWritten = try c.decodeIfPresent(String.self, forKey: .lastWritten) ?? ""
    }
}

/// One most-read row: an entity page and how many `read` ledger events name
/// it (an app card open, an MCP recall or recall_detail — R11). `lastRead` is
/// an ISO timestamp.
struct TopEntityRead: Codable, Identifiable, Equatable {
    let entityId: String; let reads: Int; let lastRead: String
    var id: String { entityId }
    enum CodingKeys: String, CodingKey { case entityId, reads, lastRead }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decode(String.self, forKey: .entityId)
        reads = try c.decodeIfPresent(Int.self, forKey: .reads) ?? 0
        lastRead = try c.decodeIfPresent(String.self, forKey: .lastRead) ?? ""
    }
}

/// `GET /contributors/top-entities` (G124): most-written from git (bounded —
/// `commitsScanned` says how far back, R13), most-read from the ids-only
/// `read` ledger kind. Counts only, by the 2026-09-03 ruling.
struct TopEntities: Codable {
    let written: [TopEntityWrite]
    let read: [TopEntityRead]
    let commitsScanned: Int
    let range: String
    enum CodingKeys: String, CodingKey { case written, read, commitsScanned, range }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        written = (try? c.decodeIfPresent([TopEntityWrite].self, forKey: .written)) ?? []
        read = (try? c.decodeIfPresent([TopEntityRead].self, forKey: .read)) ?? []
        commitsScanned = try c.decodeIfPresent(Int.self, forKey: .commitsScanned) ?? 0
        range = try c.decodeIfPresent(String.self, forKey: .range) ?? "all"
    }
}
