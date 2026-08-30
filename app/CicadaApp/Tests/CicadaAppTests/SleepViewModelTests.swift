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
    private func sleepStatus(status: String, stage: Int, totalStages: Int = 5) throws -> SleepStatusResponse {
        let json = """
        {"status":"\(status)","cycleId":"c1","startedAt":null,"progress":null,"error":null,
         "indexWarning":null,"stage":\(stage),"totalStages":\(totalStages),"episodesTotal":0,
         "entitiesCreated":0,"entitiesUpdated":0,"relationshipsCreated":0,"skillsDetected":0}
        """
        return try JSONDecoder().decode(SleepStatusResponse.self, from: Data(json.utf8))
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
}
