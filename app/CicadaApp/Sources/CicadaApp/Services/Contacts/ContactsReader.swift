import Foundation
import Observation

/// G154 (round 4 decision 12) — the Mac's address book, read by the APP through the Contacts framework and posted to
/// the backend, which enriches the person pages Cicada already has (never a new one, R-SR8).
///
/// Copies `CalendarReader`'s rules: never read before the person clicks Connect and macOS says yes; an empty read is
/// never posted; a refusal is said in the server's own words; Disconnect stops everything and deletes nothing.
/// **When it reads (R-SR10):** on Connect; on launch only when `currentHistoryToken` moved or the last post for this
/// bank is a day old (a person page Sleep created since may now match); on `CNContactStoreDidChange`, debounced; on a
/// bank switch; on Sync now. Each run reports into `SyncActivity`, so × stops it (R-SR11).
@MainActor
@Observable
final class ContactsReader {
    enum Status: Equatable { case off, denied, syncing, watching, empty, failed(String) }

    nonisolated static let enabledKey = "cicada.contacts.enabled"
    nonisolated static let channel = "contacts-local"

    private(set) var status: Status = .off
    private(set) var enabled: Bool

    @ObservationIgnored private let store: ContactStore
    @ObservationIgnored private let api: any ContactsSyncAPI
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let activity: SyncActivity?
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let debounce: Duration
    @ObservationIgnored private let staleAfter: TimeInterval
    @ObservationIgnored private let bank: @MainActor () -> String
    @ObservationIgnored private var watch: Task<Void, Never>?
    @ObservationIgnored private var pending: Task<Void, Never>?
    @ObservationIgnored private var running: Task<String, Error>?

    init(store: ContactStore = SystemContactStore(), api: any ContactsSyncAPI = APIClient.shared,
         defaults: UserDefaults = .standard, activity: SyncActivity? = nil, now: @escaping () -> Date = Date.init,
         debounce: Duration = .seconds(30), staleAfter: TimeInterval = 24 * 3600,
         bank: @escaping @MainActor () -> String = { "default" }) {
        self.store = store; self.api = api; self.defaults = defaults; self.activity = activity; self.now = now
        self.debounce = debounce; self.staleAfter = staleAfter; self.bank = bank
        self.enabled = defaults.bool(forKey: Self.enabledKey)
    }

    private func tokenKey(_ bank: String) -> String { "cicada.contacts.\(bank).token" }
    private func lastPostKey(_ bank: String) -> String { "cicada.contacts.\(bank).lastPost" }

    /// R-SR10, pure: post on launch when this bank never got one, the book moved, or a day passed.
    nonisolated static func shouldPostOnLaunch(token: Data?, stored: Data?, lastPost: Date?, now: Date,
                                               staleAfter: TimeInterval) -> Bool {
        guard let lastPost else { return true }
        guard let token, token == stored else { return true }
        return now.timeIntervalSince(lastPost) >= staleAfter
    }

    func start() {
        guard enabled else { status = .off; return }
        guard store.access() == .granted else { status = .denied; return }
        arm()
        status = .watching
        let bank = self.bank()
        if Self.shouldPostOnLaunch(token: store.historyToken(), stored: defaults.data(forKey: tokenKey(bank)),
                                   lastPost: defaults.object(forKey: lastPostKey(bank)) as? Date, now: now(),
                                   staleAfter: staleAfter) {
            Task { await self.sync() }
        }
    }

    func connect() async {
        guard await store.requestAccess(), store.access() == .granted else {
            defaults.set(false, forKey: Self.enabledKey)
            enabled = false
            status = .denied
            return
        }
        defaults.set(true, forKey: Self.enabledKey)
        enabled = true
        arm()
        await sync()
    }

    func disconnect() {
        defaults.set(false, forKey: Self.enabledKey)
        enabled = false
        watch?.cancel(); pending?.cancel(); running?.cancel()
        watch = nil; pending = nil
        status = .off
    }

    func syncNow() async { await sync() }

    /// Sync now from a card: the one-line answer, or a sentence saying Connect comes first.
    func syncNowReporting() async throws -> String {
        guard enabled else { throw BrowserImportActions.ImportActionError.failed(Copy.contactsConnectFirst) }
        return try await sync().get()
    }

    func bankChanged() async { guard enabled else { return }; await sync() }

    func cancel() { running?.cancel() }

    @discardableResult
    func sync() async -> Result<String, Error> {
        if let running { return await running.result }
        guard enabled else { return .failure(CancellationError()) }
        // Access can be taken away in System Settings while Cicada runs; a read without it comes back empty. Said as
        // the refusal it is — a `CancellationError` here read "Stopped" on a card's Sync now (`ChannelActions.sync`).
        guard store.access() == .granted else {
            status = .denied
            return .failure(BrowserImportActions.ImportActionError.failed(Copy.contactsDenied))
        }
        let bank = self.bank()
        let task = Task { @MainActor [weak self] () throws -> String in
            guard let self else { throw CancellationError() }
            return try await self.perform(bank: bank)
        }
        running = task
        activity?.began(Self.channel, detail: Copy.contactsReading, cancel: { [weak self] in self?.cancel() })
        status = .syncing
        let result = await task.result
        running = nil
        activity?.ended(Self.channel)
        switch result {
        case .success:
            status = enabled ? .watching : .off
        case .failure(let error) where SyncCancellation.isCancellation(error):
            status = enabled ? .watching : .off
        case .failure(ContactsReadError.empty):
            status = .empty
        case .failure(let error):
            status = enabled ? .failed(Self.failureMessage(error)) : .off
        }
        return result
    }

    private func perform(bank: String) async throws -> String {
        let token = store.historyToken()
        let records = await store.snapshot()
        try Task.checkCancellation()
        guard !records.isEmpty else { throw ContactsReadError.empty }
        activity?.progressed(Self.channel, detail: Copy.contactsMatching(records.count))
        let result = try await api.syncLocalContacts(ContactsSyncPayload(contacts: records))
        try Task.checkCancellation()
        defaults.set(token, forKey: tokenKey(bank))
        defaults.set(now(), forKey: lastPostKey(bank))
        return Copy.contactsSyncedSummary(contacts: result.contacts, people: result.people)
    }

    private func arm() {
        guard watch == nil else { return }
        let stream = store.changes()
        watch = Task { [weak self] in
            for await _ in stream { self?.scheduleDebounced() }
        }
    }

    private func scheduleDebounced() {
        guard enabled else { return }
        pending?.cancel()
        pending = Task { [weak self, debounce] in
            try? await Task.sleep(for: debounce)
            guard !Task.isCancelled else { return }
            await self?.sync()
        }
    }

    /// A 409's detail is written for the person (Sleep tidying, the demo refusal) — `ProjectWriteFailure.detail`.
    static func failureMessage(_ error: Error) -> String {
        if error is URLError { return Copy.sourceBackendDown }
        guard let api = error as? APIError else { return Copy.contactsSyncFailed }
        switch api {
        case .httpError(409, let body): return ProjectWriteFailure.detail(body) ?? Copy.contactsSyncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.sourceNeedsUpdate
        case .serverUnreachable: return Copy.sourceBackendDown
        default: return Copy.contactsSyncFailed
        }
    }
}
