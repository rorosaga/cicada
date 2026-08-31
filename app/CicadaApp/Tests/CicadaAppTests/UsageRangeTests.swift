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
        let vm = UsageViewModel(store: Store(cache: tempCache(), api: FakeSyncAPI()))
        XCTAssertTrue(vm.isEmptyRange)
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
