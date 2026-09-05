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
    var schedule: ScheduleConfig = ScheduleConfig(mode: "manual", hour: 3, minute: 0)
    var errorMessage: String?

    /// G125 R4 — the consolidation history the Sleep page's history card
    /// lists, newest first. Loaded alongside everything else in `load()`.
    var history: [SleepHistoryEntry] = []
    /// G125 R12 — a history row's expanded detail, cached by commit hash so
    /// a second click on an already-open row is a dictionary hit rather than
    /// a second fetch. Never evicted within a session; a bank switch simply
    /// starts a new `SleepViewModel`.
    var details: [String: SleepCycleDetail] = [:]
    /// Which history row's detail is disclosed, if any (Task 7's
    /// `ConsolidationHistoryCard`). `nil` means every row is collapsed.
    var expanded: String?

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

    /// PR #19 review: `SleepView` fires an untracked `load()` for every live
    /// `store.status.episodes.unprocessed` change (reconciling the queue rows
    /// against a count that can move faster than one round-trip). Overlapping
    /// calls have no cancellation or identity guard, so a slower, older
    /// response can land after a newer one and repaint the queue with stale
    /// rows. Bumped at the top of every `load()`; mirrors
    /// `UsageViewModel.rangeToken` — a response whose token no longer matches
    /// current lost the race and is dropped.
    private var loadToken = 0

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

    /// Injectable, same reasoning as `fetchSleepStatus`. Defaults to the
    /// real `POST /sleep/cancel` call.
    private let requestCancel: () async throws -> SleepCancelResponse

    /// Injectable, same reasoning as `fetchSleepStatus`. Defaults to the
    /// real `GET /sleep/history` call.
    private let fetchHistory: () async throws -> [SleepHistoryEntry]

    /// Injectable, same reasoning as `fetchSleepStatus`. Defaults to the
    /// real `GET /sleep/history/{commit}` call.
    private let fetchDetail: (String) async throws -> SleepCycleDetail

    /// True from the moment `cancel()` is called until the poll loop
    /// observes the cycle has actually stopped (whether because of the
    /// cancel or otherwise) — cooperative cancellation means the backend
    /// doesn't flip to idle the instant the request lands, so this is what
    /// drives the button's "Cancelling…" state in between.
    var cancelRequested = false

    init(
        store: Store,
        fetchSleepStatus: @escaping () async throws -> SleepStatusResponse = {
            try await APIClient.shared.fetchSleepStatus()
        },
        requestCancel: @escaping () async throws -> SleepCancelResponse = {
            try await APIClient.shared.cancelSleep()
        },
        fetchHistory: @escaping () async throws -> [SleepHistoryEntry] = {
            try await APIClient.shared.fetchSleepHistory(limit: 15)
        },
        fetchDetail: @escaping (String) async throws -> SleepCycleDetail = {
            try await APIClient.shared.fetchSleepCycleDetail($0)
        }
    ) {
        self.store = store
        self.fetchSleepStatus = fetchSleepStatus
        self.requestCancel = requestCancel
        self.fetchHistory = fetchHistory
        self.fetchDetail = fetchDetail
    }

    /// `/sleep/status` isn't a Store domain, so this mirrors the Store's
    /// `.status` loading state as the closest available signal (both come
    /// from the same "how healthy is my view of Sleep" question).
    var isLoading: Bool { store.status.isEmpty && store.status.isRefreshing }

    var isRunning: Bool { status?.status == "running" }

    /// Review fix L2: `cancelRequested` (above) is this CLIENT's own tap —
    /// instant feedback with no network round-trip, but blind to a cancel
    /// requested by another client, or one already in flight before this
    /// app instance started or reconnected. `status?.cancelRequested` is
    /// the server's own authoritative flag. ORing them means whichever one
    /// knows first wins — never stuck disagreeing with the server the way
    /// reading only the local flag could.
    var isCancelling: Bool { cancelRequested || (status?.cancelRequested ?? false) }

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
        loadToken &+= 1
        let token = loadToken

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
        // `loadHistory()` does its own guarding against `loadToken` (reading,
        // never bumping, it — only `load()` mints a new generation) rather
        // than being raced through a fourth do/catch here, so it can also be
        // called on its own later (a history-only refresh) with the exact
        // same staleness protection.
        async let historyTask: Void = loadHistory()

        // Each result is guarded individually rather than once at the end —
        // the fetches race independently, and a newer `load()` call can
        // start (and even finish) while any one of them is still in flight.
        // Without the per-assignment check, a call that lost the race on
        // `status` could still win on `episodes` (or vice versa), stitching
        // together a queue view that never existed on the server at any one
        // moment.
        do {
            let s = try await statusTask
            if token == loadToken { status = s }
        } catch {
            if token == loadToken { errorMessage = "Status: \(error.localizedDescription)" }
        }
        do {
            let e = try await episodesTask
            if token == loadToken { episodes = e }
        } catch {
            if token == loadToken { errorMessage = "Episodes: \(error.localizedDescription)" }
        }
        do {
            let sc = try await scheduleTask
            if token == loadToken { schedule = sc }
        } catch {
            if token == loadToken { errorMessage = "Schedule: \(error.localizedDescription)" }
        }
        await historyTask

        // A superseded call must not make poll-loop decisions either — the
        // newer call (or one still in flight) owns that now.
        guard token == loadToken else { return }

        // If a cycle is already running (e.g. started by the daily cron
        // before the user opened the page), attach to it — but only if
        // nothing is polling yet (see the guard above).
        if pollTask == nil, isRunning {
            startPolling()
        }
    }

    /// Reload the consolidation history list (G125 R4) — called from
    /// `load()`'s fourth `async let`, and safe to call again on its own (a
    /// history-only refresh). Reads, never bumps, `loadToken`: only `load()`
    /// mints a new generation, so a call here rides whatever generation is
    /// already current and drops its own result if a newer `load()` lands
    /// first — same protection the three original fetches get, applied
    /// without a fifth counter.
    func loadHistory() async {
        let token = loadToken
        do {
            let h = try await fetchHistory()
            if token == loadToken { history = h }
        } catch {
            if token == loadToken { errorMessage = "History: \(error.localizedDescription)" }
        }
    }

    /// Fetch one cycle's detail and cache it by commit hash (G125 R12) — a
    /// second click on an already-expanded history row is a dictionary hit,
    /// never a second network round trip. Guarded the same way as
    /// `loadHistory()`: a bank switch that starts a fresh `load()` while
    /// this fetch is still in flight must not paint another bank's cycle
    /// into the detail the user is now looking at.
    func loadDetail(_ commit: String) async {
        if details[commit] != nil { return }
        let token = loadToken
        do {
            let d = try await fetchDetail(commit)
            if token == loadToken { details[commit] = d }
        } catch {
            if token == loadToken { errorMessage = "History: \(error.localizedDescription)" }
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

    /// Request cooperative cancellation of the running cycle. Does not touch
    /// `status` locally — the cycle keeps running until it reaches its next
    /// safe point, and the already-armed poll loop (a cycle must be running
    /// for `isRunning` to gate this call) is what observes and reports the
    /// eventual running -> idle edge, exactly like a normal completion.
    func cancel() async {
        // `isCancelling`, not the bare local flag: a cancel already known to
        // the server (another client, or one already in flight before this
        // instance connected) must also short-circuit a redundant POST —
        // the request is idempotent server-side, but there is nothing to gain
        // from sending it again.
        guard isRunning, !isCancelling else { return }
        cancelRequested = true
        do {
            _ = try await requestCancel()
        } catch {
            // The request itself failed (network blip) — nothing was
            // actually cancelled, so un-arm the button rather than leaving
            // it stuck on "Cancelling…" for a request that never landed.
            cancelRequested = false
            errorMessage = "Cancel: \(error.localizedDescription)"
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
        // A brand-new cycle never carries over a stale "Cancelling…" from
        // whatever the button was showing for the previous one.
        cancelRequested = false
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
                        // The cycle actually stopped (cancelled or not) —
                        // clear the button's "Cancelling…" state now rather
                        // than waiting for the next `startPolling()`.
                        self.cancelRequested = false
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
