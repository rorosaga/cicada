import Foundation
import Observation

protocol WatchHistorySyncAPI: Sendable {
    func syncWatchHistory(_ payload: WatchHistoryPayload) async throws -> WatchHistorySyncResult
}

extension APIClient: WatchHistorySyncAPI {}

/// G71 (owner 2026-10-16) — "my watch later videos from youtube and maybe also sync history": the YouTube videos the
/// person watches in Chrome, read by the APP from Chrome's own History on this Mac and posted to the backend, which
/// keeps one episode per day of what was watched (never a saved link).
///
/// **Its own switch.** What a person watches is a stronger ask than a bookmark, so it is never folded into Chrome's
/// bookmark consent: `cicada.browserWatch.enabled.chrome-youtube-history`, off until turned on. Nothing is read before.
/// **When it reads.** On turning on, on launch, on a bank switch, on Sync now, and — while on — every `checkInterval`
/// when the History file's size or modification time moved since the last pass (a stat, nothing read). Chrome writes
/// History on nearly every page load, so an FSEvents watch would fire constantly for pages that are not videos; a
/// slow, stat-gated check costs nothing and keeps the record current within minutes.
/// **What leaves the app.** YouTube video pages only (`ChromeWatchHistoryReader`): their link, title and visit time.
/// **Cursor.** Per bank, the last Chrome visit id posted — advanced only after the backend accepted a batch, so a
/// failed post is read again; the backend's day records make any re-read harmless.
@MainActor
@Observable
final class WatchHistoryWatcher {
    nonisolated static let channel = "chrome-youtube-history"
    nonisolated static let browser = "chrome"
    nonisolated static let profile = "Default"

    enum Status: Equatable { case off, missing, watching, syncing, failed(String) }

    private(set) var status: Status = .off
    private(set) var enabled: Bool
    /// What memory holds (the backend's count after the last sync) — the row's line.
    private(set) var videos: Int?

    @ObservationIgnored private let lights: BrowserWatcher?
    @ObservationIgnored private let activity: SyncActivity?
    @ObservationIgnored private let api: any WatchHistorySyncAPI
    @ObservationIgnored private let reader: ChromeWatchHistoryReader
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let checkInterval: Duration
    @ObservationIgnored private let maxPasses: Int
    @ObservationIgnored private let bank: @MainActor () -> String
    @ObservationIgnored private var ticker: Task<Void, Never>?
    @ObservationIgnored private var running: Task<String, Error>?
    /// The memory `running` reads for: a run for another memory is stopped and replaced, never joined (G183(d)).
    @ObservationIgnored private var runningBank: String?
    @ObservationIgnored private var lastStamp: String?

    init(lights: BrowserWatcher? = nil, activity: SyncActivity? = nil, api: any WatchHistorySyncAPI = APIClient.shared,
         reader: ChromeWatchHistoryReader = ChromeWatchHistoryReader(historyFile: ChromeWatchHistoryReader.standardHistory),
         defaults: UserDefaults = .standard, checkInterval: Duration = .seconds(600), maxPasses: Int = 20,
         bank: @escaping @MainActor () -> String = { "default" }) {
        self.lights = lights
        self.activity = activity
        self.api = api
        self.reader = reader
        self.defaults = defaults
        self.checkInterval = checkInterval
        self.maxPasses = maxPasses
        self.bank = bank
        self.enabled = defaults.bool(forKey: BrowserWatchPolicy.enabledKey(Self.channel))
    }

    nonisolated static var enabledKey: String { BrowserWatchPolicy.enabledKey(channel) }
    /// Per connection (G181 phase 3): a server has not had what This Mac's backend had.
    nonisolated static func cursorKey(_ bank: String) -> String {
        ServerConnection.current.scoped("cicada.watchHistory.\(bank).cursor")
    }

    func cursor(bank: String) -> Int64 { Int64(defaults.integer(forKey: Self.cursorKey(bank))) }

    /// On launch: arm and catch up, only if the person turned it on.
    func start() {
        guard enabled else { status = .off; publish(); return }
        arm()
        Task { await self.run(force: false) }
    }

    /// The switch, on: the consent, then one read (forced: the person just asked).
    func enable() async {
        defaults.set(true, forKey: Self.enabledKey)
        enabled = true
        arm()
        await run(force: true)
    }

    /// The switch, off: stops reading. Deletes nothing — the days already in memory stay.
    func disable() {
        defaults.set(false, forKey: Self.enabledKey)
        enabled = false
        ticker?.cancel(); ticker = nil
        running?.cancel()
        status = .off
        publish()
    }

    func syncNow() async throws -> String {
        guard enabled else { throw BrowserImportActions.ImportActionError.failed(Copy.watchHistoryTurnOnFirst) }
        return try await run(force: true).get()
    }

    /// A bank switch: the new memory reads from its own cursor.
    func bankChanged() async {
        guard enabled else { return }
        await run(force: true)
    }

    func cancel() { running?.cancel() }

    @discardableResult
    func run(force: Bool) async -> Result<String, Error> {
        let bank = self.bank()
        if let running {
            // One at a time per memory; a second caller shares the run. A run still reading for the memory the person
            // switched away from is stopped instead: its writes are bound to that memory (refused there now), and the
            // memory on screen reads past its own cursor at once rather than after the old run (G183(d)).
            if runningBank == bank { return await running.result }
            running.cancel()
        }
        guard enabled else { return .failure(CancellationError()) }
        let stamp = Self.stamp(reader.historyFile)
        if !force, stamp != nil, stamp == lastStamp { return .success(Copy.watchHistorySynced(added: 0)) }
        let task = Task { @MainActor [weak self] () throws -> String in
            guard let self else { throw CancellationError() }
            // G183(d): every batch names the memory whose cursor it reads from and advances.
            return try await BankScope.bound(to: bank) { try await self.perform(bank: bank) }
        }
        running = task
        runningBank = bank
        activity?.began(Self.channel, detail: Copy.watchHistoryReading, cancel: { [weak self] in self?.cancel() })
        status = .syncing
        publish()
        let result = await task.result
        guard running == task else { return result }   // replaced by the memory on screen's own run: it owns the row
        running = nil
        runningBank = nil
        activity?.ended(Self.channel)
        switch result {
        case .success:
            lastStamp = stamp
            status = .watching
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

    private func perform(bank: String) async throws -> String {
        var added = 0
        for _ in 0..<maxPasses {
            let reader = self.reader
            let since = cursor(bank: bank)
            let pass = try await Task.detached(priority: .utility) { try reader.read(after: since) }.value
            try Task.checkCancellation()
            if !pass.visits.isEmpty {
                activity?.progressed(Self.channel, detail: Copy.watchHistorySending(pass.visits.count))
                let result = try await api.syncWatchHistory(WatchHistoryPayload(
                    browser: Self.browser, profile: Self.profile, visits: pass.visits))
                try Task.checkCancellation()
                added += result.added
                videos = result.videos
            }
            defaults.set(Int(pass.lastVisitId), forKey: Self.cursorKey(bank))
            if !pass.hasMore { break }
        }
        return Copy.watchHistorySynced(added: added)
    }

    /// While on: every `checkInterval`, a pass only when the History file moved (a stat — nothing read).
    private func arm() {
        guard ticker == nil else { return }
        let interval = checkInterval
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: interval)
                guard !Task.isCancelled, let self, self.enabled else { return }
                await self.run(force: false)
            }
        }
    }

    /// Size and modification time of the History file, or nil when it cannot be stat'ed.
    nonisolated static func stamp(_ file: URL) -> String? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: file.path),
              let size = attrs[.size] as? NSNumber, let date = attrs[.modificationDate] as? Date else { return nil }
        return "\(size.int64Value):\(date.timeIntervalSince1970)"
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
        if error is WatchHistoryReadError { return Copy.watchHistoryUnreadable }
        if error is URLError { return Copy.sourceBackendDown }
        guard let api = error as? APIError else { return Copy.watchHistorySyncFailed }
        switch api {
        case .httpError(409, let body): return ProjectWriteFailure.detail(body) ?? Copy.watchHistorySyncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.sourceNeedsUpdate
        case .serverUnreachable: return Copy.sourceBackendDown
        default: return Copy.watchHistorySyncFailed
        }
    }
}
