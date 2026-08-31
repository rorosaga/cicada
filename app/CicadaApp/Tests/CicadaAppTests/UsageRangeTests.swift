import XCTest
@testable import CicadaApp

/// G68 §2.5 — switching the range must never leave the previous range's
/// numbers under the new label, and a slow earlier request must never
/// overwrite the newer one it lost to.
@MainActor
final class UsageRangeTests: XCTestCase {

    private func tempCache() -> SnapshotCache {
        SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString))
    }

    private func summary(tokens: Int) -> ConsumptionSummary {
        var s = ConsumptionSummary()
        s.tokens = tokens
        s.invocations = tokens
        return s
    }

    private func emptyStats() throws -> ConsumptionStats {
        let json = """
        {"byModel":[],"byStage":[],"byConnection":[],"byBank":[],
         "hourHistogram":[0],"series":[],"range":"30d"}
        """
        return try JSONDecoder().decode(ConsumptionStats.self, from: Data(json.utf8))
    }

    func testStaleRangeResponseIsDiscarded() async throws {
        var gate: CheckedContinuation<Void, Never>?
        let stats = try emptyStats()
        let vm = UsageViewModel(store: Store(cache: tempCache(), api: FakeSyncAPI())) { range in
            if range == "30d" { await withCheckedContinuation { gate = $0 } }
            return (self.summary(tokens: range == "30d" ? 30 : 90),
                    stats,
                    ConsumptionConnections(connections: [], range: range))
        }

        vm.range = "30d"                                  // parks on the gate
        try await Task.sleep(for: .milliseconds(120))
        vm.range = "90d"                                  // wins the race
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertEqual(vm.summary.tokens, 90)

        gate?.resume()                                    // the loser lands last
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertEqual(vm.summary.tokens, 90, "a stale range overwrote the current one")
        XCTAssertFalse(vm.isLoadingRange)
    }

    /// While a range is in flight the page shows a spinner, not the previous
    /// range's totals under the new label.
    func testNumbersAreBlankedWhileANewRangeIsInFlight() async throws {
        var gate: CheckedContinuation<Void, Never>?
        let stats = try emptyStats()
        let vm = UsageViewModel(store: Store(cache: tempCache(), api: FakeSyncAPI())) { range in
            await withCheckedContinuation { gate = $0 }
            return (self.summary(tokens: 90), stats, ConsumptionConnections(connections: [], range: range))
        }

        vm.range = "90d"
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertTrue(vm.isLoadingRange)
        XCTAssertEqual(vm.summary.tokens, 0, "showed the old range's numbers under the new label")

        gate?.resume()
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertEqual(vm.summary.tokens, 90)
    }

    func testAnAllZeroRangeIsReportedAsEmptyRatherThanAWallOfZeroes() async throws {
        let store = Store(cache: tempCache(), api: FakeSyncAPI())
        // A genuinely-loaded, confirmed all-zero month — not merely the
        // never-loaded default — is what should read as "empty".
        store.consumption.value = ConsumptionBundle(
            summary: ConsumptionSummary(),
            calendar: ConsumptionCalendar(days: [], weeks: 53),
            stats: try emptyStats(),
            connections: ConsumptionConnections(connections: [], range: "month"),
            harness: HarnessStats(claudeCode: nil, codex: nil)
        )
        let vm = UsageViewModel(store: store)
        XCTAssertTrue(vm.isEmptyRange)
    }

    /// PR #19 review: before `Store.bootstrap()` ever populates
    /// `store.consumption`, `summary` already falls back to an all-zero
    /// `ConsumptionSummary()`. Without gating on whether the month actually
    /// loaded, `isEmptyRange` read `true` on a brand-new store and Activity
    /// briefly claimed "No usage this month" before the real data arrived.
    func testMonthIsNotReportedAsEmptyBeforeItHasEverLoaded() async throws {
        let store = Store(cache: tempCache(), api: FakeSyncAPI())
        XCTAssertNil(store.consumption.value, "precondition: nothing has loaded yet")
        let vm = UsageViewModel(store: store)
        XCTAssertFalse(vm.isEmptyRange, "must not claim empty before bootstrap ever loads the month")
    }

    /// Same gap, non-default range: before the first `loadRange()` response
    /// lands, `rangeSummary` is nil and `summary` falls back to all-zero —
    /// that must not read as a confirmed-empty range either.
    func testNonDefaultRangeIsNotReportedAsEmptyBeforeItHasEverLoaded() async throws {
        var gate: CheckedContinuation<Void, Never>?
        let stats = try emptyStats()
        let vm = UsageViewModel(store: Store(cache: tempCache(), api: FakeSyncAPI())) { range in
            await withCheckedContinuation { gate = $0 }
            return (self.summary(tokens: 0), stats, ConsumptionConnections(connections: [], range: range))
        }

        vm.range = "30d"
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertFalse(vm.isEmptyRange, "the 30d range hasn't landed yet — it isn't confirmed empty")

        gate?.resume()
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertTrue(vm.isEmptyRange, "now it really has loaded and really is all-zero")
    }

    /// M2: a failed range fetch left `summary` all-zero (the `catch` path
    /// never sets `rangeSummary`, so `summary` falls back to a blank
    /// `ConsumptionSummary()`), so `isEmptyRange` read `true` and the page
    /// rendered the error banner AND "No usage in this range" for a range it
    /// never actually loaded.
    func testFailedRangeFetchIsNotReportedAsEmpty() async throws {
        struct Boom: Error {}
        let vm = UsageViewModel(store: Store(cache: tempCache(), api: FakeSyncAPI())) { _ in throw Boom() }

        vm.range = "30d"
        try await Task.sleep(for: .milliseconds(120))

        XCTAssertNotNil(vm.errorMessage)
        XCTAssertFalse(vm.isEmptyRange, "a failed fetch must not also claim the range is empty")
    }

    /// The controller ruling on top of the brief: the race guard is not just
    /// an identity check on arrival — the superseded range's own `Task` must
    /// actually be cancelled the moment a newer range wins, not merely have
    /// its result ignored. Pinned by observing `Task.isCancelled` from
    /// inside the abandoned fetch once it's finally allowed to resume.
    func testChangingRangeCancelsThePreviousInFlightFetch() async throws {
        var gate: CheckedContinuation<Void, Never>?
        var wasCancelledOnResume: Bool?
        let stats = try emptyStats()
        let vm = UsageViewModel(store: Store(cache: tempCache(), api: FakeSyncAPI())) { range in
            if range == "30d" {
                await withCheckedContinuation { gate = $0 }
                wasCancelledOnResume = Task.isCancelled
            }
            return (self.summary(tokens: range == "30d" ? 30 : 90),
                    stats,
                    ConsumptionConnections(connections: [], range: range))
        }

        vm.range = "30d"
        try await Task.sleep(for: .milliseconds(120))
        vm.range = "90d"                                  // must cancel the "30d" Task
        try await Task.sleep(for: .milliseconds(120))

        gate?.resume()
        try await Task.sleep(for: .milliseconds(120))

        XCTAssertEqual(wasCancelledOnResume, true, "the superseded range fetch's Task must be cancelled")
    }
}
