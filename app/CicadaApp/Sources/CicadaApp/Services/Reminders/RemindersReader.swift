import Foundation
import Observation

/// G219 — the Reminders app's lists, read by the APP through EventKit and posted to the backend, which stages them like
/// every other source; one way, never written back (ruling 38). `CalendarReader`'s rules: never read before the person
/// clicks Connect and macOS says yes; then on launch, on a change (debounced), every few hours while Cicada runs, after
/// a bank switch, and on Refresh. Only the lists the person ticks are read — none is ticked for them — and Disconnect
/// stops all of it and deletes nothing.
///
/// The Disconnect race (2026-10-23, #448): a read that was in flight when the person pressed Disconnect never posts
/// and never turns the row back on. Every await re-checks a generation that Disconnect bumps, so a read begun before
/// it is dropped wherever it is — before the post, and after it.
@MainActor
@Observable
final class RemindersReader {
    enum Status: Equatable {
        case off, denied
        /// Connected, but no list is ticked: nothing is read.
        case noLists
        case syncing
        case synced(at: Date, reminders: Int)
        case failed(String)
    }

    nonisolated static let channel = "reminders-local"
    nonisolated static let enabledKey = "cicada.reminders.enabled"
    nonisolated static let listsKey = "cicada.reminders.lists"
    nonisolated static let sharedKey = "cicada.reminders.shared"

    /// The app's one reader (the Sources rows and Refresh share it, `AppleNotesWatcher.shared`'s precedent); tests
    /// make their own.
    static let shared = RemindersReader()

    private(set) var status: Status = .off
    /// Every list on this Mac, for the picker — read only after Connect.
    private(set) var available: [RemindersListInfo] = []
    private(set) var ticked: Set<String>
    private(set) var sharedLists: Set<String>
    private(set) var enabled: Bool

    var isEnabled: Bool { enabled }
    /// On for the catalogue: connected and at least one list ticked — otherwise nothing will arrive (#448's rule).
    var isOn: Bool { enabled && !ticked.isEmpty && status != .denied }

    @ObservationIgnored private let store: RemindersStore
    @ObservationIgnored private let api: RemindersSyncAPI
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let debounce: Duration
    @ObservationIgnored private let period: Duration
    @ObservationIgnored private var watch: Task<Void, Never>?
    @ObservationIgnored private var periodic: Task<Void, Never>?
    @ObservationIgnored private var pending: Task<Void, Never>?
    @ObservationIgnored private var inFlight = false
    @ObservationIgnored private var again = false
    /// Bumped by Disconnect: a read that began under an older generation never posts or sets a status.
    @ObservationIgnored private var generation = 0

    init(store: RemindersStore = EventKitRemindersStore(), api: RemindersSyncAPI = APIClient.shared,
         defaults: UserDefaults = .standard, now: @escaping () -> Date = Date.init,
         debounce: Duration = .seconds(10), period: Duration = .seconds(3 * 60 * 60)) {
        self.store = store; self.api = api; self.defaults = defaults; self.now = now
        self.debounce = debounce; self.period = period
        enabled = defaults.bool(forKey: Self.enabledKey)
        ticked = Set(defaults.stringArray(forKey: Self.listsKey) ?? [])
        sharedLists = Set(defaults.stringArray(forKey: Self.sharedKey) ?? [])
    }

    /// On launch: arm and catch up, only if the person connected before and macOS still says yes.
    func start() {
        guard enabled else { status = .off; return }
        guard store.access() == .granted else { status = .denied; return }
        arm()
        Task { await refreshLists(); await sync() }
    }

    func connect() async {
        let gen = generation
        guard await store.requestAccess(), store.access() == .granted else {
            guard gen == generation else { return }
            setEnabled(false)
            status = .denied
            return
        }
        guard gen == generation else { return }
        setEnabled(true)
        arm()
        await refreshLists()
        await sync()
    }

    func disconnect() {
        generation += 1
        setEnabled(false)
        watch?.cancel(); periodic?.cancel(); pending?.cancel()
        watch = nil; periodic = nil; pending = nil
        again = false
        status = .off
    }

    func syncNow() async { guard enabled else { return }; await sync() }

    /// A bank switch: the new memory gets the reminders too (409 if it is the demo, said in words).
    func bankChanged() async { await syncNow() }

    /// The picker's tick. Ticking reads at once; unticking stops reading that list and deletes nothing.
    func setTicked(_ id: String, _ on: Bool) async {
        if on { ticked.insert(id) } else { ticked.remove(id) }
        defaults.set(ticked.sorted(), forKey: Self.listsKey)
        await syncNow()
    }

    /// "Others add to this list": its items are read as not the person's own words.
    func setShared(_ id: String, _ on: Bool) async {
        if on { sharedLists.insert(id) } else { sharedLists.remove(id) }
        defaults.set(sharedLists.sorted(), forKey: Self.sharedKey)
        if ticked.contains(id) { await syncNow() }
    }

    func refreshLists() async {
        guard enabled, store.access() == .granted else { return }
        let gen = generation
        let lists = await store.lists()
        guard gen == generation else { return }
        available = lists.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending }
    }

    private func setEnabled(_ value: Bool) {
        enabled = value
        defaults.set(value, forKey: Self.enabledKey)
    }

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
        guard enabled else { return }
        pending?.cancel()
        pending = Task { [weak self, debounce] in
            try? await Task.sleep(for: debounce)
            guard !Task.isCancelled else { return }
            await self?.refreshLists()
            await self?.syncNow()
        }
    }

    private func current(_ gen: Int) -> Bool { gen == generation && enabled }

    private func sync() async {
        guard !inFlight else { again = true; return }
        inFlight = true
        defer { inFlight = false }
        let gen = generation
        repeat {
            again = false
            guard current(gen) else { return }
            guard store.access() == .granted else { status = .denied; return }
            guard !ticked.isEmpty else { status = .noLists; return }
            status = .syncing
            let lists = await store.lists()
            guard current(gen) else { return }
            // A read whose ticked lists are not there (EventKit not ready, access gone mid-read, every ticked list
            // deleted) is never posted: the backend would tombstone every reminder of the lists it names.
            let named = lists.filter { ticked.contains($0.id) }.map { list -> RemindersListInfo in
                var list = list
                list.shared = sharedLists.contains(list.id)
                return list
            }
            guard !named.isEmpty else {
                status = lists.isEmpty ? .failed(Copy.remindersNotReady) : .noLists
                return
            }
            let since = RemindersMapper.completedSince(now: now())
            let records = await store.reminders(in: Set(named.map(\.id)), completedSince: since)
            guard current(gen) else { return }
            let payload = RemindersSyncPayload(completedSince: RemindersMapper.iso(since), lists: named,
                                               reminders: RemindersMapper.ticked(records, lists: Set(named.map(\.id))))
            do {
                let result = try await api.syncLocalReminders(payload)
                guard current(gen) else { return }   // Disconnect landed while this one was posting
                status = .synced(at: now(), reminders: result.created + result.updated + result.unchanged)
            } catch {
                guard current(gen) else { return }
                status = .failed(Self.failureMessage(error))
                return
            }
        } while again && current(gen)
    }

    /// `CalendarReader.failureMessage`'s mapping, in Reminders' words.
    static func failureMessage(_ error: Error) -> String {
        if error is URLError { return Copy.calendarBackendDown }
        guard let api = error as? APIError else { return Copy.remindersSyncFailed }
        switch api {
        case .httpError(409, let body): return ProjectWriteFailure.detail(body) ?? Copy.remindersSyncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.remindersNeedsUpdate
        case .serverUnreachable: return Copy.calendarBackendDown
        default: return Copy.remindersSyncFailed
        }
    }
}

/// The route on the one API client (`APIClient.syncLocalReminders`), so the reader's default talks to the live backend.
extension APIClient: RemindersSyncAPI {}
