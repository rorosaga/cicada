import Foundation

/// Change detection for the app (§5.3).
///
/// Holds one long-lived SSE connection to `GET /sync/events`. A `version` event
/// is diffed against the last-seen vector by the `Store`, which refreshes only
/// the affected domains; a `sleep` event is merged straight into the status
/// snapshot so the menu bar's stage dots move in real time.
///
/// When the stream drops (backend restart, sleep/wake, network blip) it
/// reconnects with 1 s → 30 s backoff and, *while waiting*, polls
/// `GET /sync/version` every 3 s so the app is never more than a few seconds
/// stale even with SSE unavailable.
@MainActor
final class SyncEngine {
    private let api: any SyncAPI
    private unowned var store: Store!
    private var task: Task<Void, Never>?

    /// Backoff bounds and the disconnected poll cadence, in seconds.
    private let minBackoff: Double = 1
    private let maxBackoff: Double = 30
    private let pollInterval: Double = 3

    init(api: any SyncAPI) {
        self.api = api
    }

    /// Called by `Store.init` — the two own each other, so this breaks the
    /// initialisation cycle. `store` is `unowned`: the Store outlives us.
    func attach(store: Store) {
        self.store = store
    }

    var isRunning: Bool { task != nil }

    func start() {
        task?.cancel()
        task = Task { [weak self] in
            var backoff = self?.minBackoff ?? 1
            while !Task.isCancelled {
                guard let self else { return }
                do {
                    let (lines, _) = try await self.api.syncEventLines()
                    self.store.isConnected = true
                    backoff = self.minBackoff
                    var parser = SSEParser()
                    for try await line in lines {
                        if Task.isCancelled { return }
                        guard let event = parser.feed(line) else { continue }
                        await self.handle(event)
                    }
                } catch {
                    // Fall through to the reconnect/poll loop below.
                }
                if Task.isCancelled { return }
                self.store.isConnected = false
                // Poll while we wait out the backoff so the UI keeps moving.
                let until = Date().addingTimeInterval(backoff)
                repeat {
                    if Task.isCancelled { return }
                    if let version = try? await self.api.fetchSyncVersion() {
                        await self.store.apply(version: version)
                    }
                    try? await Task.sleep(for: .seconds(self.pollInterval))
                } while Date() < until && !Task.isCancelled
                backoff = min(self.maxBackoff, backoff * 2)
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
        store?.isConnected = false
    }

    private func handle(_ event: SSEEvent) async {
        let data = Data(event.data.utf8)
        switch event.name {
        case "version":
            guard let version = try? JSONDecoder().decode(VersionVector.self, from: data) else { return }
            await store.apply(version: version)
        case "sleep":
            guard let payload = try? JSONDecoder().decode(SleepEventPayload.self, from: data) else { return }
            store.applySleepEvent(payload)
        default:
            break   // ping / unknown — the connection staying alive is the point
        }
    }
}
