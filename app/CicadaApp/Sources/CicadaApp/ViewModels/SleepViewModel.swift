import Foundation
import Observation

/// Backs the Sleep dashboard. `status` is still `SleepStatusResponse` (richer
/// than `Store.status`'s `StatusSnapshot.Sleep` — it carries the per-cycle
/// counters `/sleep/status` returns that `/status` doesn't), so this VM keeps
/// fetching it via `APIClient` rather than projecting it wholesale. What it
/// *does* take from the Store: an immediate, synchronous read of
/// `store.status.value?.sleep.status` to know whether a cycle is already
/// running without waiting on its own network round-trip, and as an extra
/// signal (alongside its own poll) for noticing the running → idle edge.
/// `episodes`/`schedule` have no Store domain (§brief) — those stay plain
/// `APIClient` fetches.
@Observable
@MainActor
final class SleepViewModel {
    private let store: Store

    var status: SleepStatusResponse?
    var episodes: [EpisodeQueueItem] = []
    var schedule: ScheduleConfig = ScheduleConfig(enabled: false, hour: 3, minute: 0)
    var errorMessage: String?

    /// Hook fired exactly once when a cycle transitions ``running`` -> ``idle``
    /// without an exception. The app wires this to ``GraphViewModel.loadGraph``
    /// so Topics/Graph reflect post-Sleep state without an app restart.
    /// Errors and warnings still trigger the close-out, but the closure is
    /// only invoked when ``error == nil``; warnings (e.g. partial LEANN
    /// rebuild failures) do not block the refresh because the markdown
    /// graph itself was committed successfully.
    var onCycleCompleted: (@MainActor () async -> Void)?

    /// Fired on every poll tick during a running cycle (after ``status`` is
    /// updated) so the menu-bar bookworm advances its 1..5 stage dots within
    /// ~1s instead of waiting for the App's coarse 30s status poll.
    var onStatusChanged: (@MainActor (SleepStatusResponse) -> Void)?

    private var pollTask: Task<Void, Never>?

    init(store: Store) {
        self.store = store
    }

    /// `/sleep/status` isn't a Store domain, so this mirrors the Store's
    /// `.status` loading state as the closest available signal (both come
    /// from the same "how healthy is my view of Sleep" question).
    var isLoading: Bool { store.status.isEmpty && store.status.isRefreshing }

    var isRunning: Bool { status?.status == "running" }

    var progressFraction: Double {
        guard let s = status, s.totalStages > 0 else { return 0 }
        return min(1.0, Double(s.stage) / Double(s.totalStages))
    }

    var lastError: String? { status?.error }

    var queuedEpisodes: [EpisodeQueueItem] {
        episodes.filter { !$0.processed }
    }

    var processedEpisodes: [EpisodeQueueItem] {
        episodes.filter { $0.processed }
    }

    /// Load everything the Sleep dashboard needs: current status, the full
    /// episode list (queued + processed), and the persisted schedule.
    ///
    /// If the Store's own `/status` snapshot already shows a cycle running
    /// (pushed over SSE, or hydrated from disk), start polling immediately
    /// rather than waiting on this function's own `/sleep/status` round-trip
    /// — a scheduled run that started while the app was closed becomes live
    /// the instant this view appears, not one network round-trip later.
    func load() async {
        errorMessage = nil
        if store.status.value?.sleep.status == "running" {
            startPolling()
        }

        async let statusTask = APIClient.shared.fetchSleepStatus()
        async let episodesTask = APIClient.shared.fetchEpisodeQueue()
        async let scheduleTask = APIClient.shared.fetchSchedule()

        do {
            status = try await statusTask
        } catch {
            errorMessage = "Status: \(error.localizedDescription)"
        }
        do {
            episodes = try await episodesTask
        } catch {
            errorMessage = "Episodes: \(error.localizedDescription)"
        }
        do {
            schedule = try await scheduleTask
        } catch {
            errorMessage = "Schedule: \(error.localizedDescription)"
        }

        // If a cycle is already running (e.g. started by the daily cron
        // before the user opened the page), attach to it. startPolling()
        // cancels any prior poll task so this is idempotent.
        if isRunning {
            startPolling()
        }
    }

    func triggerManually() async {
        errorMessage = nil
        do {
            _ = try await APIClient.shared.triggerSleep()
            startPolling()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func updateSchedule(_ new: ScheduleConfig) async {
        do {
            schedule = try await APIClient.shared.updateSchedule(new)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Single source of truth for sleep polling. Old TopBarControls had its
    /// own while-loop + local @State; that's gone. Anywhere that wants to
    /// know "is a cycle running?" reads this view model.
    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard let self else { return }
                do {
                    let next = try await APIClient.shared.fetchSleepStatus()
                    self.status = next
                    // Feed live sleep progress to the menu-bar bookworm so its
                    // stage dots advance at the 1s poll cadence.
                    self.onStatusChanged?(next)
                    // Stop on whichever signal says idle first: this poll's
                    // own fetch, or the Store's SSE-pushed status/sleepEvent
                    // (can beat a 1s-cadence poll by a beat).
                    let storeIdle = self.store.status.value?.sleep.status == "idle"
                        || self.store.sleepEvent?.status == "idle"
                    if next.status == "idle" || storeIdle {
                        // Refresh the queue once the cycle finishes so the
                        // UI shows the post-cycle state.
                        await self.load()
                        // Fire the post-cycle hook exactly once. We do not
                        // refresh the graph if the cycle ended in error
                        // (Sleep crashed mid-pipeline → markdown graph could
                        // be in a half-written state and we'd rather show
                        // the pre-cycle snapshot than a partial one). A
                        // warning-only completion still committed entities,
                        // so it counts as success for refresh purposes.
                        if (next.error ?? "").isEmpty {
                            await self.onCycleCompleted?()
                        }
                        return
                    }
                } catch {
                    // Transient poll errors are expected when the API is
                    // momentarily unreachable. Keep polling.
                    continue
                }
            }
        }
    }

}
