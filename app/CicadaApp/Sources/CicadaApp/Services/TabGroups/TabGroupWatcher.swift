import Foundation
import Observation

/// Round 4 (G160 first slice; decisions addendum 3) — Chrome's open tab groups, read by the APP from the default
/// profile's `Sessions/` file and posted to the backend, which keeps one snapshot episode per group.
///
/// **Its own switch (R-SR3).** A tab group says what the person is doing right now — a stronger ask than a bookmark —
/// so it is never folded into Chrome's bookmark consent: `cicada.browserWatch.enabled.chrome-tab-groups`, off until
/// turned on, with no signature fallback. Nothing is read before that.
/// **When it reads (R-SR7).** On turning on, on launch, on a bank switch, on Sync now, and on an FSEvents change in
/// `Sessions/` (Chrome appends to one file, which a directory `DispatchSource` never sees) — debounced 10 s and
/// floored at 60 s. A digest of the posted snapshot per bank skips an unchanged one.
/// **What it says.** Its status lights every surface through `BrowserWatcher.publish` (R-LS26), and each run reports
/// into `SyncActivity`, so the row says "Syncing now" with an × that stops it (R-SR11).
@MainActor
@Observable
final class TabGroupWatcher {
    nonisolated static let channel = "chrome-tab-groups"
    nonisolated static let browser = "chrome"
    nonisolated static let profile = "Default"
    nonisolated static var chromeSessions: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Google/Chrome/Default/Sessions")
    }

    enum Status: Equatable { case off, missing, watching, syncing, failed(String) }

    private(set) var status: Status = .off
    private(set) var enabled: Bool
    /// What the last read found — the Integrations row's tags. Live, from this Mac; never read back from a bank.
    private(set) var groups: [ChromiumTabGroup] = []

    @ObservationIgnored private let lights: BrowserWatcher?
    @ObservationIgnored private let activity: SyncActivity?
    @ObservationIgnored private let api: any TabGroupsSyncAPI
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let directory: URL
    @ObservationIgnored private let debounce: Duration
    @ObservationIgnored private let minimumInterval: Duration
    @ObservationIgnored private let makeWatch: FolderWatchFactory
    @ObservationIgnored private let bank: @MainActor () -> String
    @ObservationIgnored private var watch: FSEventsWatch?
    @ObservationIgnored private var pending: Task<Void, Never>?
    @ObservationIgnored private var running: Task<String, Error>?
    @ObservationIgnored private var lastStarted: ContinuousClock.Instant?

    init(lights: BrowserWatcher? = nil, activity: SyncActivity? = nil, api: any TabGroupsSyncAPI = APIClient.shared,
         defaults: UserDefaults = .standard, directory: URL = TabGroupWatcher.chromeSessions,
         debounce: Duration = .seconds(10), minimumInterval: Duration = .seconds(60),
         makeWatch: FolderWatchFactory? = nil, bank: @escaping @MainActor () -> String = { "default" }) {
        self.lights = lights
        self.activity = activity
        self.api = api
        self.defaults = defaults
        self.directory = directory
        self.debounce = debounce
        self.minimumInterval = minimumInterval
        self.makeWatch = makeWatch ?? { path, onChange in FSEventsWatch(path: path, handler: onChange) }
        self.bank = bank
        self.enabled = defaults.bool(forKey: BrowserWatchPolicy.enabledKey(Self.channel))
    }

    private var enabledKey: String { BrowserWatchPolicy.enabledKey(Self.channel) }
    private func digestKey(_ bank: String) -> String { "cicada.tabGroups.\(bank).digest" }

    /// On launch: arm and catch up, only if the person turned it on.
    func start() {
        guard enabled else { status = .off; publish(); return }
        arm()
        Task { await self.run(force: false) }
    }

    /// The switch, on: the consent, then one read (forced: the person just asked).
    func enable() async {
        defaults.set(true, forKey: enabledKey)
        enabled = true
        arm()
        await run(force: true)
    }

    /// The switch, off: stops reading and forgets the tags. Deletes nothing — a group already in memory stays.
    func disable() {
        defaults.set(false, forKey: enabledKey)
        enabled = false
        watch?.stop(); watch = nil
        pending?.cancel(); pending = nil
        running?.cancel()
        groups = []
        status = .off
        publish()
    }

    func syncNow() async throws -> String {
        guard enabled else { throw BrowserImportActions.ImportActionError.failed(Copy.tabGroupsTurnOnFirst) }
        return try await run(force: true).get()
    }

    /// A bank switch: the new memory gets the snapshot too (its digest is its own).
    func bankChanged() async {
        guard enabled else { return }
        await run(force: false)
    }

    /// R-SR11 — × stops the run in flight; the switch stays on and no digest is recorded.
    func cancel() { running?.cancel() }

    @discardableResult
    func run(force: Bool) async -> Result<String, Error> {
        if let running { return await running.result }   // one at a time; a second caller shares the run
        guard enabled else { return .failure(CancellationError()) }
        let bank = self.bank()
        let task = Task { @MainActor [weak self] () throws -> String in
            guard let self else { throw CancellationError() }
            return try await self.perform(bank: bank, force: force)
        }
        running = task
        lastStarted = .now
        activity?.began(Self.channel, detail: Copy.tabGroupsReading, cancel: { [weak self] in self?.cancel() })
        status = .syncing
        publish()
        let result = await task.result
        running = nil
        activity?.ended(Self.channel)
        switch result {
        case .success:
            status = .watching
            if watch == nil { arm() }   // the folder may have appeared since launch
        case .failure(let error) where SyncCancellation.isCancellation(error):
            status = enabled ? .watching : .off
        case .failure(let error as BrowserFileError):
            if case .missing = error { status = .missing } else { status = .failed(error.userMessage) }
        case .failure(let error):
            status = .failed(Self.failureMessage(error))
        }
        publish()
        return result
    }

    private func perform(bank: String, force: Bool) async throws -> String {
        let directory = self.directory
        let found = try await Task.detached(priority: .utility) {
            try ChromiumSessionFiles.newestGroups(in: directory)
        }.value
        try Task.checkCancellation()
        groups = found
        let payload = TabGroupsPayload(browser: Self.browser, profile: Self.profile, groups: found)
        let digest = TabGroupsPayload.digest(payload, bank: bank)
        if !force, defaults.string(forKey: digestKey(bank)) == digest { return Copy.tabGroupsUpToDate }
        activity?.progressed(Self.channel, detail: Copy.tabGroupsSending(found.count))
        let result = try await api.syncTabGroups(payload)
        try Task.checkCancellation()
        defaults.set(digest, forKey: digestKey(bank))
        return Copy.tabGroupsSynced(groups: result.groups, tabs: result.tabs)
    }

    private func arm() {
        guard watch == nil else { return }
        watch = makeWatch(directory.path) { [weak self] in self?.changed() }
    }

    private func changed() {
        guard enabled else { return }
        pending?.cancel()
        pending = Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(for: self.debounce)
            guard !Task.isCancelled else { return }
            if let last = self.lastStarted {
                let elapsed = ContinuousClock.now - last
                if elapsed < self.minimumInterval { try? await Task.sleep(for: self.minimumInterval - elapsed) }
                guard !Task.isCancelled else { return }
            }
            await self.run(force: false)
        }
    }

    private func publish() {
        let light: BrowserWatchState = switch status {
        case .off: .off
        case .missing: .absent
        case .watching: .watching
        case .syncing: .syncing
        case .failed: .failed
        }
        lights?.publish(light, error: nil, for: Self.channel)
    }

    /// A 409's detail is the server's own sentence (the demo refusal) — `ProjectWriteFailure.detail`, the one parser.
    static func failureMessage(_ error: Error) -> String {
        if error is ChromiumSessionError { return Copy.tabGroupsUnreadable }
        if error is URLError { return Copy.sourceBackendDown }
        guard let api = error as? APIError else { return Copy.tabGroupsSyncFailed }
        switch api {
        case .httpError(409, let body): return ProjectWriteFailure.detail(body) ?? Copy.tabGroupsSyncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.sourceNeedsUpdate
        case .serverUnreachable: return Copy.sourceBackendDown
        default: return Copy.tabGroupsSyncFailed
        }
    }
}
