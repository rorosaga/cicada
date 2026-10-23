import Foundation

/// G219 — what the app sends `POST /sources/reminders-local/sync`: the lists the person ticked, and every open reminder
/// in them plus those completed in the last 90 days. The app reads EventKit (the ~/Library rail); the backend stages,
/// scrubs and tombstones. Every time is ISO-8601 with its offset; a due date with no time is a bare day.
struct RemindersListInfo: Codable, Equatable, Hashable, Sendable, Identifiable {
    let id: String
    let title: String
    let account: String?
    /// The person said others add to this list, so its items are never read as their own words.
    var shared: Bool = false
}

struct ReminderRecord: Encodable, Equatable, Sendable {
    let id: String
    let listId: String
    let title: String
    let notes: String?
    let url: String?
    let created: String?
    let lastModified: String?
    let completed: Bool
    let completedAt: String?
    let due: String?
    let dueAllDay: Bool
    let priority: Int
}

struct RemindersSyncPayload: Encodable, Equatable, Sendable {
    let completedSince: String
    let lists: [RemindersListInfo]
    let reminders: [ReminderRecord]
}

/// The route's answer; lenient, so a backend one field ahead or behind never fails the sync.
struct RemindersSyncResult: Decodable, Equatable, Sendable {
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

/// The seam over EventKit, so a test never asks macOS for anything (`CalendarStore`'s pattern). Access reuses
/// `CalendarAccess`: the same five answers EventKit gives for either entity type.
protocol RemindersStore: AnyObject, Sendable {
    func access() -> CalendarAccess
    func requestAccess() async -> Bool
    /// Every reminder list on this Mac (the picker's rows), never their reminders.
    func lists() async -> [RemindersListInfo]
    /// The open reminders of `lists`, plus those completed since `completedSince`, already mapped.
    func reminders(in lists: Set<String>, completedSince: Date) async -> [ReminderRecord]
    func changes() -> AsyncStream<Void>
}

protocol RemindersSyncAPI: Sendable {
    func syncLocalReminders(_ payload: RemindersSyncPayload) async throws -> RemindersSyncResult
}

/// Pure pieces of the EventKit mapping.
enum RemindersMapper {
    static let notesCap = 10_000
    /// Completed reminders older than this are left out of the read (owner ruling 38: the last 90 days).
    static let completedDays = 90

    static func completedSince(now: Date, calendar: Calendar = .current) -> Date {
        calendar.date(byAdding: .day, value: -completedDays, to: now) ?? now
    }

    static func iso(_ date: Date, timeZone: TimeZone = .current) -> String {
        CalendarEventMapper.iso(date, timeZone: timeZone)
    }

    /// `calendarItemExternalIdentifier`, else the local identifier — the backend keys `reminders-local:<id>`.
    static func id(externalId: String?, itemId: String) -> String {
        (externalId?.isEmpty == false ? externalId : nil) ?? itemId
    }

    /// A due date as written: a bare day when the reminder has no time (`yyyy-MM-dd`), else the instant with its
    /// offset. Nil components (year/month/day missing) are no due date.
    static func due(_ components: DateComponents?, calendar: Calendar = .current) -> (String?, Bool) {
        guard let components, let year = components.year, let month = components.month, let day = components.day
        else { return (nil, false) }
        if components.hour == nil {
            return (String(format: "%04d-%02d-%02d", year, month, day), true)
        }
        var comps = components
        comps.calendar = comps.calendar ?? calendar
        guard let date = comps.date else { return (String(format: "%04d-%02d-%02d", year, month, day), true) }
        return (iso(date, timeZone: comps.timeZone ?? calendar.timeZone), false)
    }

    /// Only the ticked lists' reminders, one per id, the first kept (a reminder never sits in two lists, but a
    /// repeated id would overwrite its own episode on every read).
    static func ticked(_ records: [ReminderRecord], lists: Set<String>) -> [ReminderRecord] {
        var seen = Set<String>()
        return records.filter { lists.contains($0.listId) && seen.insert($0.id).inserted }
    }

    static func notes(_ raw: String?) -> String? { CalendarEventMapper.notes(raw) }
}
