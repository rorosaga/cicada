import Foundation
import Observation

@Observable
@MainActor
final class SleepViewModel {
    var status: SleepStatusResponse?
    var episodes: [EpisodeQueueItem] = []
    var schedule: ScheduleConfig = ScheduleConfig(enabled: false, hour: 3, minute: 0)
    var isLoading = false
    var errorMessage: String?

    /// Hook fired exactly once when a cycle transitions ``running`` -> ``idle``
    /// without an exception. The app wires this to ``GraphViewModel.loadGraph``
    /// so Topics/Graph reflect post-Sleep state without an app restart.
    /// Errors and warnings still trigger the close-out, but the closure is
    /// only invoked when ``error == nil``; warnings (e.g. partial LEANN
    /// rebuild failures) do not block the refresh because the markdown
    /// graph itself was committed successfully.
    var onCycleCompleted: (@MainActor () async -> Void)?

    private var pollTask: Task<Void, Never>?

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
    /// If the snapshot reveals that a cycle is already running — either
    /// because the user triggered it from elsewhere, or because the APScheduler
    /// daily cron fired while the app was closed — we start polling so the
    /// dashboard becomes a *live* view instead of a stale snapshot. Without
    /// this, a scheduled run would render frozen until the user clicked
    /// "Run now" manually, defeating the entire point of the page.
    func load() async {
        isLoading = true
        defer { isLoading = false }

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
        if status?.status == "running" {
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
                    if next.status == "idle" {
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
