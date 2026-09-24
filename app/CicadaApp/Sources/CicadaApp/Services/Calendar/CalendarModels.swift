import Foundation

/// Round-4 D2 (C6) — what the app sends `POST /sources/calendar-local/sync`. Encodable in C6's exact shape; every
/// time is ISO-8601 with its offset. The app reads the calendars (EventKit, the ~/Library rail); the backend stages,
/// scrubs and tombstones.
struct CalendarInfo: Encodable, Equatable, Sendable {
    let id: String
    let title: String
    let account: String?
}

struct CalendarEventRecord: Encodable, Equatable, Sendable {
    let id: String
    let calendarId: String
    let title: String
    let start: String
    let end: String
    let allDay: Bool
    let location: String?
    let notes: String?
    let url: String?
    let attendees: [String]?
    let organizer: String?
    let lastModified: String?
}

struct CalendarSyncPayload: Encodable, Equatable, Sendable {
    struct Window: Encodable, Equatable, Sendable {
        let from: String
        let to: String
    }
    let window: Window
    let calendars: [CalendarInfo]
    let events: [CalendarEventRecord]
}

/// C6's answer; lenient, so a backend one field ahead or behind never fails the sync.
struct CalendarSyncResult: Decodable, Equatable, Sendable {
    var created = 0
    var updated = 0
    var unchanged = 0
    var tombstoned = 0
    var bank = ""

    init(created: Int = 0, updated: Int = 0, unchanged: Int = 0, tombstoned: Int = 0, bank: String = "") {
        self.created = created; self.updated = updated; self.unchanged = unchanged
        self.tombstoned = tombstoned; self.bank = bank
    }

    enum CodingKeys: String, CodingKey { case created, updated, unchanged, tombstoned, bank }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        created = c.lenient(.created, 0)
        updated = c.lenient(.updated, 0)
        unchanged = c.lenient(.unchanged, 0)
        tombstoned = c.lenient(.tombstoned, 0)
        bank = c.lenient(.bank, "")
    }
}

enum CalendarAccess: Equatable, Sendable { case notDetermined, granted, denied, restricted, writeOnly }

/// The seam over EventKit (C7), so a test never asks macOS for anything.
protocol CalendarStore: AnyObject, Sendable {
    func access() -> CalendarAccess
    func requestAccess() async -> Bool
    /// Every calendar and every event between the two dates, already mapped.
    func snapshot(from: Date, to: Date) async -> (calendars: [CalendarInfo], events: [CalendarEventRecord])
    func changes() -> AsyncStream<Void>
}

protocol CalendarSyncAPI: Sendable {
    func syncLocalCalendar(_ payload: CalendarSyncPayload) async throws -> CalendarSyncResult
}

/// Pure pieces of the EventKit mapping (R-FA11).
enum CalendarEventMapper {
    static let notesCap = 10_000
    static let daysBack = 30
    static let daysAhead = 60

    static func window(now: Date, calendar: Calendar = .current) -> (from: Date, to: Date) {
        (calendar.date(byAdding: .day, value: -daysBack, to: now) ?? now,
         calendar.date(byAdding: .day, value: daysAhead, to: now) ?? now)
    }

    static func iso(_ date: Date, timeZone: TimeZone) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = timeZone
        return f.string(from: date)
    }

    /// C6 — `calendarItemExternalIdentifier`, plus `|` and the occurrence's start for a recurring event (every
    /// occurrence shares the external id); the local identifier only when the external one is missing.
    static func id(externalId: String?, itemId: String, recurring: Bool, occurrence: Date, timeZone: TimeZone) -> String {
        let base = (externalId?.isEmpty == false ? externalId : nil) ?? itemId
        return recurring ? "\(base)|\(iso(occurrence, timeZone: timeZone))" : base
    }

    /// A person as the calendar names them: their display name, else their address without `mailto:`.
    static func person(name: String?, url: URL?) -> String? {
        if let name = name?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty { return name }
        guard let url else { return nil }
        let raw = url.absoluteString
        let address = raw.lowercased().hasPrefix("mailto:") ? String(raw.dropFirst("mailto:".count)) : raw
        return address.isEmpty ? nil : address
    }

    static func notes(_ raw: String?) -> String? {
        guard let raw, !raw.isEmpty else { return nil }
        return raw.count > notesCap ? String(raw.prefix(notesCap)) : raw
    }
}
