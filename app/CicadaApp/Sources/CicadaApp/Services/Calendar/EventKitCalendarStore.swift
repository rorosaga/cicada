import EventKit
import Foundation

/// Round-4 D2 (C6, C7) — the real `CalendarStore`: every calendar account on this Mac (iCloud, Google, Exchange, a
/// local calendar) through the one EventKit store the Calendar app itself reads.
///
/// Why app-side: the calendars live under `~/Library`, and the rail is that the APP reads `~/Library` and the backend
/// parses bytes — the launchd backend has no calendar access and needs none; it stages what this posts. Nothing is
/// ever written back: Cicada only reads, though macOS offers reading only as "full access" since macOS 14
/// (`requestFullAccessToEvents`), so that is the one prompt the person sees.
final class EventKitCalendarStore: CalendarStore, @unchecked Sendable {
    /// One store for the app's life: `EKEventStoreChanged` is posted by the store instance that is watched, and a
    /// fresh store per read would re-load every calendar from scratch.
    private let store = EKEventStore()

    func access() -> CalendarAccess {
        switch EKEventStore.authorizationStatus(for: .event) {
        case .fullAccess: .granted
        case .writeOnly: .writeOnly
        case .denied: .denied
        case .restricted: .restricted
        case .notDetermined: .notDetermined
        // The pre-14 `.authorized` shares `.fullAccess`'s raw value, so it is already the first case above.
        @unknown default: .denied
        }
    }

    func requestAccess() async -> Bool {
        (try? await store.requestFullAccessToEvents()) ?? false
    }

    /// Every event in the window, mapped through `CalendarEventMapper`. Detached at utility priority: a 90-day window
    /// over several accounts can take a noticeable moment, and it must never run on the main actor.
    func snapshot(from: Date, to: Date) async -> (calendars: [CalendarInfo], events: [CalendarEventRecord]) {
        let store = self.store
        return await Task.detached(priority: .utility) {
            let calendars = store.calendars(for: .event)
            let predicate = store.predicateForEvents(withStart: from, end: to, calendars: nil)
            let events = store.events(matching: predicate)
            let infos = calendars.map {
                CalendarInfo(id: $0.calendarIdentifier, title: $0.title, account: $0.source?.title)
            }
            let records = CalendarEventMapper.firstById(events.map(Self.record(_:)))
            return (infos, records)
        }.value
    }

    /// `EKEventStoreChanged` for this store, as a stream the reader debounces (R-FA11).
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

    /// One `EKEvent` in C6's shape: each time with the event's own offset (a floating event takes this Mac's), a
    /// recurring occurrence keyed by its start, people by name else address.
    private static func record(_ event: EKEvent) -> CalendarEventRecord {
        let zone = event.timeZone ?? .current
        let start: Date = event.startDate ?? Date()
        let end: Date = event.endDate ?? start
        let organizer = event.organizer.flatMap { CalendarEventMapper.person(name: $0.name, url: $0.url) }
        let attendees = event.attendees?.compactMap { CalendarEventMapper.person(name: $0.name, url: $0.url) }
        return CalendarEventRecord(
            id: CalendarEventMapper.id(externalId: event.calendarItemExternalIdentifier,
                                       itemId: event.calendarItemIdentifier,
                                       // A detached occurrence (one moved or edited) can report no rules while
                                       // sharing its series' UID; without its start it would collapse onto the
                                       // bare UID with every other detached one (finding 3).
                                       recurring: event.hasRecurrenceRules || event.isDetached,
                                       occurrence: event.occurrenceDate ?? start, timeZone: zone),
            calendarId: event.calendar?.calendarIdentifier ?? "",
            title: event.title ?? "",
            start: CalendarEventMapper.iso(start, timeZone: zone),
            end: CalendarEventMapper.iso(end, timeZone: zone),
            allDay: event.isAllDay,
            location: event.location?.isEmpty == false ? event.location : nil,
            notes: CalendarEventMapper.notes(event.notes),
            url: event.url?.absoluteString,
            attendees: attendees?.isEmpty == false ? attendees : nil,
            organizer: organizer,
            lastModified: event.lastModifiedDate.map { CalendarEventMapper.iso($0, timeZone: zone) })
    }
}
