@preconcurrency import EventKit
import Foundation

/// G219 — the real `RemindersStore`: every reminder list on this Mac (iCloud, Exchange, a local list) through EventKit,
/// the store the Reminders app itself reads.
///
/// Why app-side: Reminders lives under `~/Library`, and the rail is that the APP reads `~/Library` and the backend
/// parses bytes. Nothing is ever written back (ruling 38): Cicada only reads, though macOS offers reminders only as
/// "full access" (`requestFullAccessToReminders`, macOS 14) — there is no read-only grant, which the row says in words
/// before the one prompt.
final class EventKitRemindersStore: RemindersStore, @unchecked Sendable {
    /// One store for the app's life: `EKEventStoreChanged` is posted by the instance that is watched.
    private let store = EKEventStore()

    func access() -> CalendarAccess {
        switch EKEventStore.authorizationStatus(for: .reminder) {
        case .fullAccess: .granted
        case .writeOnly: .writeOnly
        case .denied: .denied
        case .restricted: .restricted
        case .notDetermined: .notDetermined
        @unknown default: .denied
        }
    }

    func requestAccess() async -> Bool {
        (try? await store.requestFullAccessToReminders()) ?? false
    }

    func lists() async -> [RemindersListInfo] {
        let store = self.store
        return await Task.detached(priority: .utility) {
            store.calendars(for: .reminder).map {
                RemindersListInfo(id: $0.calendarIdentifier, title: $0.title, account: $0.source?.title)
            }
        }.value
    }

    /// The ticked lists' open reminders, then those completed since the window's start — two fetches, mapped inside
    /// EventKit's own callbacks so no `EKReminder` crosses a task boundary. An empty tick reads nothing: EventKit takes
    /// no calendars as "every calendar".
    func reminders(in lists: Set<String>, completedSince: Date) async -> [ReminderRecord] {
        guard !lists.isEmpty else { return [] }
        let store = self.store
        let calendars = store.calendars(for: .reminder).filter { lists.contains($0.calendarIdentifier) }
        guard !calendars.isEmpty else { return [] }
        let open = store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: calendars)
        let done = store.predicateForCompletedReminders(withCompletionDateStarting: completedSince, ending: nil,
                                                        calendars: calendars)
        let a = await Self.fetch(store, open)
        let b = await Self.fetch(store, done)
        return RemindersMapper.ticked(a + b, lists: lists)
    }

    private static func fetch(_ store: EKEventStore, _ predicate: NSPredicate) async -> [ReminderRecord] {
        await withCheckedContinuation { continuation in
            _ = store.fetchReminders(matching: predicate) { found in
                continuation.resume(returning: (found ?? []).map(Self.record(_:)))
            }
        }
    }

    func changes() -> AsyncStream<Void> {
        let store = self.store
        return AsyncStream { continuation in
            let task = Task {
                for await _ in NotificationCenter.default.notifications(named: .EKEventStoreChanged, object: store) {
                    continuation.yield()
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private static func record(_ reminder: EKReminder) -> ReminderRecord {
        let (due, allDay) = RemindersMapper.due(reminder.dueDateComponents)
        return ReminderRecord(
            id: RemindersMapper.id(externalId: reminder.calendarItemExternalIdentifier,
                                   itemId: reminder.calendarItemIdentifier),
            listId: reminder.calendar?.calendarIdentifier ?? "",
            title: reminder.title ?? "",
            notes: RemindersMapper.notes(reminder.notes),
            url: reminder.url?.absoluteString,
            created: reminder.creationDate.map { RemindersMapper.iso($0) },
            lastModified: reminder.lastModifiedDate.map { RemindersMapper.iso($0) },
            completed: reminder.isCompleted,
            completedAt: reminder.completionDate.map { RemindersMapper.iso($0) },
            due: due, dueAllDay: allDay,
            priority: reminder.priority)
    }
}
