import XCTest
@testable import CicadaApp

/// Regression tests for the Critical review finding on `SleepViewModel`'s poll
/// loop: the running -> idle edge that fires `onCycleCompleted` must be
/// decided ONLY from the loop's own `/sleep/status` fetch, never from
/// `store.status` / `store.sleepEvent` — those can still report the
/// *previous* cycle's "idle" for a beat right after `triggerManually()`.
@MainActor
final class SleepViewModelTests: XCTestCase {

    private func tempCache() -> SnapshotCache {
        SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString))
    }

    /// Builds a `SleepStatusResponse` fixture. The type has no memberwise
    /// init (only `Codable`'s `init(from:)`), so fixtures are constructed by
    /// round-tripping through JSON.
    private func sleepStatus(
        status: String, stage: Int, totalStages: Int = 5, cancelRequested: Bool = false
    ) throws -> SleepStatusResponse {
        let json = """
        {"status":"\(status)","cycleId":"c1","startedAt":null,"progress":null,"error":null,
         "indexWarning":null,"stage":\(stage),"totalStages":\(totalStages),"episodesTotal":0,
         "entitiesCreated":0,"entitiesUpdated":0,"relationshipsCreated":0,"skillsDetected":0,
         "cancelRequested":\(cancelRequested)}
        """
        return try JSONDecoder().decode(SleepStatusResponse.self, from: Data(json.utf8))
    }

    /// Builds a `SleepHistoryEntry` fixture the same way — no memberwise
    /// init, round-tripped through JSON.
    private func historyEntry(commitHash: String, date: String = "2026-09-01") throws -> SleepHistoryEntry {
        let json = """
        {"commitHash":"\(commitHash)","date":"\(date)","message":"Sleep cycle \(date)","filesChanged":[]}
        """
        return try JSONDecoder().decode(SleepHistoryEntry.self, from: Data(json.utf8))
    }

    private func cycleDetail(commitHash: String) throws -> SleepCycleDetail {
        let json = """
        {"commitHash":"\(commitHash)","date":"2026-09-01","message":"Sleep cycle 2026-09-01","filesChanged":[]}
        """
        return try JSONDecoder().decode(SleepCycleDetail.self, from: Data(json.utf8))
    }

    /// A `Store` whose `.status` snapshot stays "idle" throughout — simulating
    /// the exact staleness window the Critical finding describes: right after
    /// `triggerManually()`, the Store hasn't yet heard about the new cycle.
    private func idleStore() -> Store {
        let api = FakeSyncAPI()
        api.replies[.status] = .value(StatusSnapshot(
            sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
            inbox: .init(total: 0, byKind: [:]),
            episodes: .init(unprocessed: 0, lastIngestedAt: nil),
            lastSleepAt: nil,
            nextSleepAt: nil
        ))
        return Store(cache: tempCache(), api: api)
    }

    func test_pollLoop_firesOnCycleCompletedExactlyOnce_afterSelfFetchedIdle() async throws {
        let store = idleStore()

        var sequence: [SleepStatusResponse] = [
            try sleepStatus(status: "running", stage: 1),
            try sleepStatus(status: "running", stage: 3),
            try sleepStatus(status: "idle", stage: 5),
        ]
        // load()'s own internal refresh (triggered from inside the poll loop
        // once idle is observed) also calls this closure; hand back the last
        // (idle) status forever once the scripted sequence is exhausted so
        // that follow-up call doesn't crash the test.
        let fetch: () async throws -> SleepStatusResponse = {
            if sequence.isEmpty { return try self.sleepStatus(status: "idle", stage: 5) }
            return sequence.removeFirst()
        }

        let vm = SleepViewModel(store: store, fetchSleepStatus: fetch)

        var completedCount = 0
        vm.onCycleCompleted = { completedCount += 1 }

        await vm.triggerManually()

        // Poll cadence is 1s; wait past three ticks (running, running, idle)
        // with margin, then assert exactly one completion fired.
        try await Task.sleep(for: .seconds(4))

        XCTAssertEqual(completedCount, 1, "onCycleCompleted must fire exactly once")
        XCTAssertEqual(vm.status?.status, "idle")
    }

    func test_pollLoop_doesNotFireEarly_whenStoreStatusStaysIdleThroughout() async throws {
        // Store never reports "running" at all (simulating the worst case:
        // the Store's SSE-pushed status/sleepEvent lag behind for the whole
        // cycle). Only the VM's own fetch sequence should matter.
        let store = idleStore()

        var sequence: [SleepStatusResponse] = [
            try sleepStatus(status: "running", stage: 1),
            try sleepStatus(status: "idle", stage: 5),
        ]
        let fetch: () async throws -> SleepStatusResponse = {
            if sequence.isEmpty { return try self.sleepStatus(status: "idle", stage: 5) }
            return sequence.removeFirst()
        }

        let vm = SleepViewModel(store: store, fetchSleepStatus: fetch)

        var completedTimestamps: [Bool] = []
        vm.onCycleCompleted = { completedTimestamps.append(vm.status?.status == "idle") }

        await vm.triggerManually()

        // Right after the trigger (before the first 1s tick), nothing should
        // have fired yet — this is the exact moment the Critical bug fired
        // early off a stale store.status/sleepEvent read.
        XCTAssertEqual(completedTimestamps.count, 0)

        try await Task.sleep(for: .seconds(3))

        XCTAssertEqual(completedTimestamps.count, 1)
        XCTAssertEqual(completedTimestamps.first, true, "must only fire once idle was actually observed")
    }

    /// Carry-over: a cycle that finishes in under a second is never observed
    /// as "running" by the 1s poll — but it still mutated the graph. After
    /// five consecutive idle ticks the loop closes out exactly once and stops.
    func test_pollLoop_firesOnceAfterFiveIdleTicks_whenRunningIsNeverObserved() async throws {
        let store = idleStore()
        let fetch: () async throws -> SleepStatusResponse = {
            try self.sleepStatus(status: "idle", stage: 5)
        }
        let vm = SleepViewModel(store: store, fetchSleepStatus: fetch)

        var completedCount = 0
        vm.onCycleCompleted = { completedCount += 1 }

        await vm.triggerManually()

        // Four ticks in, the bound has not been reached yet.
        try await Task.sleep(for: .seconds(4.5))
        XCTAssertEqual(completedCount, 0, "must not close out before the bound")

        // Fifth tick fires it; the loop then ends, so waiting five more
        // seconds must not produce a second completion.
        try await Task.sleep(for: .seconds(5.5))
        XCTAssertEqual(completedCount, 1, "exactly one completion, then the poll stops")
    }

    /// A `Store` whose `/status` reports a running cycle — `load()` re-arms the
    /// poll whenever it sees no poll in flight *and* this says "running", which
    /// is the path a wrongly-nilled `pollTask` opens up.
    private func runningStore() -> Store {
        let api = FakeSyncAPI()
        api.replies[.status] = .value(StatusSnapshot(
            sleep: .init(status: "running", stage: 2, totalStages: 5, cycleId: "c1", error: nil),
            inbox: .init(total: 0, byKind: [:]),
            episodes: .init(unprocessed: 0, lastIngestedAt: nil),
            lastSleepAt: nil, nextSleepAt: nil))
        return Store(cache: tempCache(), api: api)
    }

    /// Review fix: a loop closing out must clear `pollTask` only if it is still
    /// *its own* task. The interleaving: the user hits Run again exactly while
    /// the finishing loop is inside its close-out `load()`. Nilling the newer
    /// poll's handle would let the next `load()` re-arm a second, concurrent
    /// poll for the same cycle — and fire the completion hook twice for it.
    func test_closeOut_doesNotNilANewerPoll() async throws {
        let store = runningStore()
        var calls = 0
        var vm: SleepViewModel!
        let fetch: () async throws -> SleepStatusResponse = {
            calls += 1
            if calls == 1 { return try self.sleepStatus(status: "running", stage: 2) }
            if calls == 3 {
                // We are inside the finishing loop's close-out `load()`.
                await vm.triggerManually()
            }
            return try self.sleepStatus(status: "idle", stage: 5)
        }
        vm = SleepViewModel(store: store, fetchSleepStatus: fetch)

        var completedCount = 0
        vm.onCycleCompleted = { completedCount += 1 }

        await vm.triggerManually()
        // First cycle closes out around t=2s; the second poll reaches its idle
        // bound around t=7s and closes out too. A wrongly-nilled handle lets
        // *that* close-out's `load()` re-arm a third poll, which would fire
        // again around t=12s — so the window has to reach past it.
        try await Task.sleep(for: .seconds(15))

        XCTAssertEqual(completedCount, 2,
                       "one completion per cycle — a duplicate poll would add a third")
    }

    // MARK: PR #19 review — overlapping load() calls must not restore stale rows

    /// `SleepView` fires an untracked `load()` for every live queue-count
    /// change; with no arrival-identity guard a slower, older response can
    /// land after a newer one and repaint the queue with stale data. Mirrors
    /// `UsageRangeTests.testStaleRangeResponseIsDiscarded`: the first call
    /// parks mid-fetch, a second (newer) call runs to completion first and
    /// wins, and releasing the first call's gate afterwards must not let its
    /// now-stale response overwrite the newer one.
    func test_overlappingLoadCalls_aStaleStatusResponseIsDiscarded() async throws {
        let store = idleStore()
        var gate: CheckedContinuation<Void, Never>?
        var callCount = 0
        let fetch: () async throws -> SleepStatusResponse = {
            callCount += 1
            if callCount == 1 {
                await withCheckedContinuation { gate = $0 }   // first call parks here
                return try self.sleepStatus(status: "idle", stage: 1)
            }
            return try self.sleepStatus(status: "idle", stage: 4)
        }
        let vm = SleepViewModel(store: store, fetchSleepStatus: fetch)

        let firstLoad = Task { await vm.load() }
        try await Task.sleep(for: .milliseconds(150))     // let the first call park on the gate
        await vm.load()                                    // the newer call — wins immediately
        XCTAssertEqual(vm.status?.stage, 4, "the newer load() call must win as soon as it completes")

        gate?.resume()                                      // release the stale first call
        try await Task.sleep(for: .milliseconds(200))
        XCTAssertEqual(vm.status?.stage, 4, "a stale load() response must not overwrite the newer one")
        await firstLoad.value
    }

    // MARK: Sleep control (cancel)

    /// `cancel()` is a no-op — never calls the network — when no cycle is
    /// running. Mirrors `triggerSleep`'s own guard pattern.
    func test_cancel_isANoOp_whenNotRunning() async throws {
        let store = idleStore()
        let fetch: () async throws -> SleepStatusResponse = { try self.sleepStatus(status: "idle", stage: 0) }
        var cancelCalls = 0
        let cancel: () async throws -> SleepCancelResponse = {
            cancelCalls += 1
            return SleepCancelResponse(status: "not_running", message: "nothing running", cycleId: nil)
        }
        let vm = SleepViewModel(store: store, fetchSleepStatus: fetch, requestCancel: cancel)

        await vm.cancel()

        XCTAssertEqual(cancelCalls, 0, "cancel() must not hit the network when isRunning is false")
        XCTAssertFalse(vm.cancelRequested)
    }

    /// While a cycle is running, `cancel()` flips `cancelRequested` true
    /// immediately and calls the injected request exactly once — a second
    /// call while the first is still pending must not fire another request.
    func test_cancel_setsCancelRequestedAndCallsTheInjectedRequestOnce() async throws {
        let store = idleStore()
        let fetch: () async throws -> SleepStatusResponse = { try self.sleepStatus(status: "running", stage: 2) }
        var cancelCalls = 0
        let cancel: () async throws -> SleepCancelResponse = {
            cancelCalls += 1
            return SleepCancelResponse(status: "cancelling", message: "stopping at the next safe point", cycleId: "c1")
        }
        let vm = SleepViewModel(store: store, fetchSleepStatus: fetch, requestCancel: cancel)
        vm.status = try sleepStatus(status: "running", stage: 2)

        await vm.cancel()
        XCTAssertTrue(vm.cancelRequested)
        XCTAssertEqual(cancelCalls, 1)

        await vm.cancel()   // a second tap while still pending
        XCTAssertEqual(cancelCalls, 1, "a cancel already pending must not fire a second request")
    }

    /// A network failure on the cancel request itself un-arms the button —
    /// nothing was actually cancelled, so it must not stay stuck reading
    /// "Cancelling…" for a request that never landed.
    func test_cancel_clearsCancelRequested_whenTheRequestItselfFails() async throws {
        struct Boom: Error, LocalizedError { var errorDescription: String? { "boom" } }
        let store = idleStore()
        let fetch: () async throws -> SleepStatusResponse = { try self.sleepStatus(status: "running", stage: 2) }
        let cancel: () async throws -> SleepCancelResponse = { throw Boom() }
        let vm = SleepViewModel(store: store, fetchSleepStatus: fetch, requestCancel: cancel)
        vm.status = try sleepStatus(status: "running", stage: 2)

        await vm.cancel()

        XCTAssertFalse(vm.cancelRequested)
        XCTAssertNotNil(vm.errorMessage)
    }

    /// The poll loop's own close-out (running -> idle, whether cancelled or
    /// not) clears `cancelRequested` — the button must not still read
    /// "Cancelling…" once the cycle has actually stopped.
    func test_cancelRequested_clearsWhenThePollLoopObservesTheCycleStopped() async throws {
        let store = idleStore()
        var sequence: [SleepStatusResponse] = [
            try sleepStatus(status: "running", stage: 1),
            try sleepStatus(status: "running", stage: 2),
            try sleepStatus(status: "idle", stage: 5),
        ]
        let fetch: () async throws -> SleepStatusResponse = {
            if sequence.isEmpty { return try self.sleepStatus(status: "idle", stage: 5) }
            return sequence.removeFirst()
        }
        let cancel: () async throws -> SleepCancelResponse = {
            SleepCancelResponse(status: "cancelling", message: "stopping", cycleId: "c1")
        }
        let vm = SleepViewModel(store: store, fetchSleepStatus: fetch, requestCancel: cancel)

        await vm.triggerManually()
        // `triggerManually()` returns before the poll loop's first 1s tick —
        // `status` (and therefore `isRunning`) isn't set until that tick
        // lands, so wait past it before tapping Cancel.
        try await Task.sleep(for: .milliseconds(1300))
        XCTAssertTrue(vm.isRunning)
        await vm.cancel()
        XCTAssertTrue(vm.cancelRequested)

        try await Task.sleep(for: .seconds(3))   // past the idle tick; loop closes out
        XCTAssertFalse(vm.cancelRequested, "must clear once the cycle is actually observed stopped")
    }

    // MARK: isCancelling — review fix L2 (local flag disagreed with the server's own)

    /// The bug L2 named: `SleepQueueCard` used to read only the local
    /// `cancelRequested` flag, which is blind to a cancel the SERVER
    /// already knows about (another client, or a cancel already in flight
    /// before this app instance connected/restarted). `isCancelling` ORs
    /// the two so the button is never stuck disagreeing with the server.
    func test_isCancelling_isTrueFromServerState_evenWithoutALocalTap() async throws {
        let store = idleStore()
        let vm = SleepViewModel(store: store, fetchSleepStatus: { try self.sleepStatus(status: "running", stage: 2) })
        vm.status = try sleepStatus(status: "running", stage: 2, cancelRequested: true)

        XCTAssertTrue(vm.isCancelling)
        XCTAssertFalse(vm.cancelRequested, "the LOCAL flag stays false — this is purely the server's own state")
    }

    func test_isCancelling_isTrueFromTheLocalTap_evenBeforeTheServerConfirms() async throws {
        let store = idleStore()
        let cancel: () async throws -> SleepCancelResponse = {
            SleepCancelResponse(status: "cancelling", message: "stopping", cycleId: "c1")
        }
        let vm = SleepViewModel(
            store: store,
            fetchSleepStatus: { try self.sleepStatus(status: "running", stage: 2) },
            requestCancel: cancel
        )
        vm.status = try sleepStatus(status: "running", stage: 2, cancelRequested: false)

        await vm.cancel()

        XCTAssertTrue(vm.isCancelling)
    }

    func test_isCancelling_isFalse_whenNeitherLocalNorServerReportsIt() async throws {
        let store = idleStore()
        let vm = SleepViewModel(store: store, fetchSleepStatus: { try self.sleepStatus(status: "running", stage: 2) })
        vm.status = try sleepStatus(status: "running", stage: 2, cancelRequested: false)

        XCTAssertFalse(vm.isCancelling)
    }

    /// `cancel()` must not send a redundant request when the server ALREADY
    /// reports one pending — the request is idempotent server-side, but
    /// there's nothing to gain from sending it again.
    func test_cancel_sendsNoRedundantRequest_whenServerAlreadyReportsCancelling() async throws {
        let store = idleStore()
        var cancelCalls = 0
        let cancel: () async throws -> SleepCancelResponse = {
            cancelCalls += 1
            return SleepCancelResponse(status: "cancelling", message: "stopping", cycleId: "c1")
        }
        let vm = SleepViewModel(
            store: store,
            fetchSleepStatus: { try self.sleepStatus(status: "running", stage: 2) },
            requestCancel: cancel
        )
        vm.status = try sleepStatus(status: "running", stage: 2, cancelRequested: true)

        await vm.cancel()

        XCTAssertEqual(cancelCalls, 0)
    }

    // MARK: G125 — consolidation history (`load()`'s fourth fetch, `loadDetail`)

    func test_load_populatesHistoryFromInjectedFetchHistory() async throws {
        let store = idleStore()
        let entries = [try historyEntry(commitHash: "abc1"), try historyEntry(commitHash: "def2")]
        let vm = SleepViewModel(
            store: store,
            fetchSleepStatus: { try self.sleepStatus(status: "idle", stage: 0) },
            fetchHistory: { entries }
        )

        await vm.load()

        XCTAssertEqual(vm.history.map(\.commitHash), ["abc1", "def2"])
    }

    /// Mirrors `test_overlappingLoadCalls_aStaleStatusResponseIsDiscarded`:
    /// a slower, older `fetchHistory` call must not overwrite a newer one
    /// that already landed.
    func test_load_aStaleHistoryResponseIsDiscarded() async throws {
        let store = idleStore()
        var gate: CheckedContinuation<Void, Never>?
        var callCount = 0
        let fetchHistory: () async throws -> [SleepHistoryEntry] = {
            callCount += 1
            if callCount == 1 {
                await withCheckedContinuation { gate = $0 }   // first call parks here
                return [try self.historyEntry(commitHash: "stale")]
            }
            return [try self.historyEntry(commitHash: "fresh")]
        }
        let vm = SleepViewModel(
            store: store,
            fetchSleepStatus: { try self.sleepStatus(status: "idle", stage: 0) },
            fetchHistory: fetchHistory
        )

        let firstLoad = Task { await vm.load() }
        try await Task.sleep(for: .milliseconds(150))     // let the first call park on the gate
        await vm.load()                                    // the newer call — wins immediately
        XCTAssertEqual(vm.history.map(\.commitHash), ["fresh"])

        gate?.resume()                                      // release the stale first call
        try await Task.sleep(for: .milliseconds(200))
        XCTAssertEqual(vm.history.map(\.commitHash), ["fresh"], "a stale history response must not overwrite the newer one")
        await firstLoad.value
    }

    /// R12 — a second `loadDetail` for an already-cached commit is a
    /// dictionary hit: the injected fetch must not be called again.
    func test_loadDetail_cachesAndDoesNotRefetchOnASecondCall() async throws {
        let store = idleStore()
        var fetchCalls = 0
        let vm = SleepViewModel(
            store: store,
            fetchSleepStatus: { try self.sleepStatus(status: "idle", stage: 0) },
            fetchDetail: { commit in
                fetchCalls += 1
                return try self.cycleDetail(commitHash: commit)
            }
        )

        await vm.loadDetail("abc123")
        await vm.loadDetail("abc123")

        XCTAssertEqual(fetchCalls, 1, "a second click on an open row must not re-fetch")
        XCTAssertEqual(vm.details["abc123"]?.commitHash, "abc123")
    }
}
