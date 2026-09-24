import Foundation
import Observation

/// Round-4 D2 (C7) — the Calendar app's events, read by the APP through EventKit and posted to the backend, which
/// stages them like every other source. Never read before the person clicks Connect and macOS says yes (R-FA11);
/// then on launch, on a calendar change (debounced), every few hours while Cicada runs, after a bank switch, and on
/// Sync now. Disconnect stops all of it and deletes nothing.
@MainActor
@Observable
final class CalendarReader {
    enum Status: Equatable {
        case off, denied, syncing
        case synced(at: Date, events: Int)
        case failed(String)
    }

    static let enabledKey = "cicada.calendar.enabled"

    private(set) var status: Status = .off
    var isEnabled: Bool { defaults.bool(forKey: Self.enabledKey) }

    @ObservationIgnored private let store: CalendarStore
    @ObservationIgnored private let api: CalendarSyncAPI
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let debounce: Duration
    @ObservationIgnored private let period: Duration
    @ObservationIgnored private var watch: Task<Void, Never>?
    @ObservationIgnored private var periodic: Task<Void, Never>?
    @ObservationIgnored private var pending: Task<Void, Never>?
    @ObservationIgnored private var inFlight = false
    /// A trigger that landed while a sync was in flight: run once more after it (R-FA11), never two at once.
    @ObservationIgnored private var again = false

    init(store: CalendarStore = EventKitCalendarStore(), api: CalendarSyncAPI = APIClient.shared,
         defaults: UserDefaults = .standard, now: @escaping () -> Date = Date.init,
         debounce: Duration = .seconds(10), period: Duration = .seconds(3 * 60 * 60)) {
        self.store = store; self.api = api; self.defaults = defaults; self.now = now
        self.debounce = debounce; self.period = period
    }

    /// On launch: arm and catch up, only if the person connected before and macOS still says yes.
    func start() {
        guard isEnabled else { status = .off; return }
        guard store.access() == .granted else { status = .denied; return }
        arm()
        Task { await sync() }
    }

    func connect() async {
        guard await store.requestAccess(), store.access() == .granted else {
            defaults.set(false, forKey: Self.enabledKey)
            status = .denied
            return
        }
        defaults.set(true, forKey: Self.enabledKey)
        arm()
        await sync()
    }

    func disconnect() {
        defaults.set(false, forKey: Self.enabledKey)
        watch?.cancel(); periodic?.cancel(); pending?.cancel()
        watch = nil; periodic = nil; pending = nil
        again = false
        status = .off
    }

    func syncNow() async { guard isEnabled else { return }; await sync() }

    /// A bank switch: the new memory gets the calendar too (409 if it is the demo, said in words).
    func bankChanged() async { await syncNow() }

    private func arm() {
        guard watch == nil else { return }
        let stream = store.changes()
        watch = Task { [weak self] in
            for await _ in stream { self?.scheduleDebounced() }
        }
        periodic = Task { [weak self, period] in
            while !Task.isCancelled {
                try? await Task.sleep(for: period)
                guard !Task.isCancelled else { return }
                await self?.syncNow()
            }
        }
    }

    private func scheduleDebounced() {
        guard isEnabled else { return }
        pending?.cancel()
        pending = Task { [weak self, debounce] in
            try? await Task.sleep(for: debounce)
            guard !Task.isCancelled else { return }
            await self?.syncNow()
        }
    }

    private func sync() async {
        guard !inFlight else { again = true; return }
        inFlight = true
        defer { inFlight = false }
        repeat {
            again = false
            // Access can be taken away in System Settings while Cicada runs; a read without it comes back empty.
            guard store.access() == .granted else { status = .denied; return }
            status = .syncing
            let window = CalendarEventMapper.window(now: now())
            let snapshot = await store.snapshot(from: window.from, to: window.to)
            // R-FA11 — C6 tombstones every saved event the window no longer holds, so a read with no calendars at
            // all (EventKit not ready, access gone mid-read) is never posted: it would mark the whole window deleted.
            guard !snapshot.calendars.isEmpty else { status = .failed(Copy.calendarNotReady); return }
            let payload = CalendarSyncPayload(
                window: .init(from: CalendarEventMapper.iso(window.from, timeZone: .current),
                              to: CalendarEventMapper.iso(window.to, timeZone: .current)),
                calendars: snapshot.calendars, events: snapshot.events)
            do {
                let result = try await api.syncLocalCalendar(payload)
                guard isEnabled else { status = .off; return }   // Disconnect landed while this one was posting
                status = .synced(at: now(), events: result.created + result.updated + result.unchanged)
            } catch {
                guard isEnabled else { status = .off; return }
                status = .failed(Self.failureMessage(error))
                return
            }
        } while again && isEnabled
    }

    /// R-FA12 — a 409's detail is written for the person (the demo refusal, `ProjectWriteFailure.detail` — the one
    /// FastAPI-detail parser); a backend without C6 answers 404/405; a backend that is not up at all fails in
    /// `URLSession` itself (`URLError`: connection refused, timed out), which `APIClient` passes through unwrapped.
    static func failureMessage(_ error: Error) -> String {
        if error is URLError { return Copy.calendarBackendDown }
        guard let api = error as? APIError else { return Copy.calendarSyncFailed }
        switch api {
        case .httpError(409, let body): return ProjectWriteFailure.detail(body) ?? Copy.calendarSyncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.calendarNeedsUpdate
        case .serverUnreachable: return Copy.calendarBackendDown
        default: return Copy.calendarSyncFailed
        }
    }
}

/// C6's route on the one API client (`APIClient.syncLocalCalendar`), so the reader's default talks to the live backend.
extension APIClient: CalendarSyncAPI {}
