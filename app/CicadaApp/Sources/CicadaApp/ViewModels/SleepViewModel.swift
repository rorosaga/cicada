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

    /// Bumped by every `startPolling()`. A finishing loop clears `pollTask`
    /// only if this still matches the generation it was started with, so a
    /// newer poll (started while the old one was closing out) is never nilled
    /// out from under itself. A counter rather than `Task` identity because a
    /// `@Sendable` task closure can't capture the mutable local it is being
    /// assigned to.
    private var pollGeneration = 0

    /// Set the first time the poll loop's *own* fetch (never the Store's)
    /// observes `status == "running"`. `onCycleCompleted` fires exactly once,
    /// when this is `true` and a later self-fetched tick reports `"idle"` —
    /// this is what makes the loop immune to a Store snapshot that is still
    /// reporting the previous cycle's "idle" the instant a new one starts.
    private var hasSeenRunning = false

    /// Consecutive non-running ticks seen since the poll started without ever
    /// observing `"running"`. A cycle can finish in under a second (an empty
    /// episode queue does), in which case the loop never catches a running
    /// frame — but the graph was still mutated. After `idleTickBound` such
    /// ticks we close out exactly like a normally-observed cycle instead of
    /// polling for nothing.
    private var idleTicksSinceStart = 0
    private static let idleTickBound = 5

    /// Injectable so tests can feed a deterministic running/running/idle
    /// sequence without a live backend. Defaults to the real network call.
    private let fetchSleepStatus: () async throws -> SleepStatusResponse

    init(
        store: Store,
        fetchSleepStatus: @escaping () async throws -> SleepStatusResponse = {
            try await APIClient.shared.fetchSleepStatus()
        }
    ) {
        self.store = store
        self.fetchSleepStatus = fetchSleepStatus
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
        // Never re-arm the poll loop while one is already alive: `hasSeenRunning`
        // and the running→idle edge live only inside that loop's own task, and
        // starting a second one here would race it (and could re-fire
        // `onCycleCompleted` off a fresh, reset `hasSeenRunning`).
        if pollTask == nil, store.status.value?.sleep.status == "running" {
            startPolling()
        }

        async let statusTask = fetchSleepStatus()
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
        // before the user opened the page), attach to it — but only if
        // nothing is polling yet (see the guard above).
        if pollTask == nil, isRunning {
            startPolling()
        }
    }

    /// Start a cycle. `TriggerSleep` (§5.4) flips the Store's sleep status to
    /// `running` before the POST goes out, so the dashboard and the menu-bar
    /// bookworm react on the click; a failure restores the previous status and
    /// the Store's toast explains why.
    func triggerManually() async {
        errorMessage = nil
        if await store.perform(TriggerSleep()) {
            startPolling()
        } else {
            errorMessage = store.toast
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
        hasSeenRunning = false
        idleTicksSinceStart = 0
        pollGeneration += 1
        let generation = pollGeneration
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard let self else { return }
                do {
                    let next = try await self.fetchSleepStatus()
                    self.status = next
                    // Feed live sleep progress to the menu-bar bookworm so its
                    // stage dots advance at the 1s poll cadence.
                    self.onStatusChanged?(next)
                    // The running→idle edge is decided ONLY from this loop's
                    // own fetch — never from `store.status`/`store.sleepEvent`.
                    // Right after `triggerManually()`, the Store can still be
                    // reporting the *previous* cycle's "idle" for up to one
                    // SSE round-trip; trusting it here would fire
                    // `onCycleCompleted` after a single "running" tick. The
                    // Store may only ever *start* a poll early (see `load()`),
                    // never stop one.
                    if next.status == "running" {
                        self.hasSeenRunning = true
                    } else if !self.hasSeenRunning {
                        self.idleTicksSinceStart += 1
                    }
                    // Sub-1s cycle: never seen running, but `idleTickBound`
                    // idle ticks have gone by since the trigger. Treat it as
                    // finished — the cycle did run and did change the graph.
                    let boundReached = !self.hasSeenRunning
                        && self.idleTicksSinceStart >= Self.idleTickBound
                    if (self.hasSeenRunning && next.status == "idle") || boundReached {
                        // Refresh the queue once the cycle finishes so the
                        // UI shows the post-cycle state. `pollTask` is nilled
                        // *after* that call, not before: `load()` re-arms the
                        // poll when it sees no poll in flight, which would
                        // restart this loop (and, on the `boundReached` path,
                        // re-fire the hook every 5 ticks forever).
                        await self.load()
                        if self.pollGeneration == generation { self.pollTask = nil }
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
