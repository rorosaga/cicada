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

    // MARK: PR #19 review — tile row must not render zero-valued fallback as loaded data

    /// Before `Store.bootstrap()` ever populates `store.consumption`, the
    /// month tile row has nothing trustworthy to show — `isEmptyRange` reads
    /// `false` (it isn't confirmed empty), so without `showsProgress` the
    /// view's fallback would be the normal tile branch, rendering the
    /// zero-valued fallback `summary` as if it were real, loaded data.
    func testShowsProgressBeforeMonthHasEverLoaded() async throws {
        let store = Store(cache: tempCache(), api: FakeSyncAPI())
        let vm = UsageViewModel(store: store)
        XCTAssertTrue(vm.showsProgress, "the month tile row must not render before it has ever loaded")
    }

    /// While a non-default range fetch is in flight, `rangeSummary` is
    /// deliberately blanked (see `loadRange()`) — the tile row must show a
    /// spinner, not the zero-valued fallback under the new range's label.
    func testShowsProgressWhileANonDefaultRangeIsLoading() async throws {
        var gate: CheckedContinuation<Void, Never>?
        let stats = try emptyStats()
        let vm = UsageViewModel(store: Store(cache: tempCache(), api: FakeSyncAPI())) { range in
            await withCheckedContinuation { gate = $0 }
            return (self.summary(tokens: 90), stats, ConsumptionConnections(connections: [], range: range))
        }

        vm.range = "90d"
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertTrue(vm.showsProgress, "a range fetch is in flight — the tile row must not render")

        gate?.resume()
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertFalse(vm.showsProgress, "the range has now landed — the tile row may render")
    }

    /// Once a range has genuinely loaded — confirmed all-zero or not —
    /// `showsProgress` must clear so `isEmptyRange`/the real tile numbers can
    /// take over.
    func testShowsProgressClearsOnceARangeHasLoaded() async throws {
        let store = Store(cache: tempCache(), api: FakeSyncAPI())
        store.consumption.value = ConsumptionBundle(
            summary: summary(tokens: 12),
            calendar: ConsumptionCalendar(days: [], weeks: 53),
            stats: try emptyStats(),
            connections: ConsumptionConnections(connections: [], range: "month"),
            harness: HarnessStats(claudeCode: nil, codex: nil)
        )
        let vm = UsageViewModel(store: store)
        XCTAssertFalse(vm.showsProgress, "the month has loaded — the tile row must render its real numbers")
    }

    /// PR #19 round-4 review: a failed range fetch leaves `rangeSummary` nil
    /// forever (see M2's `testFailedRangeFetchIsNotReportedAsEmpty`), and an
    /// earlier fix made `showsProgress` stay `true` in that case so the
    /// failure would never be mistaken for a confirmed empty range or
    /// silently rendered as a wall of zeroes — but "stays true" means "keeps
    /// spinning forever", which is its own bug (Devin round 4): the tile row
    /// never reaches an error state, just an eternal `ProgressView`.
    /// `showsProgress` must instead clear once the attempt is *done*
    /// (success or failure) so the error can render; not falling through to
    /// zero-valued data is now the job of the view's own error branch (see
    /// `AdvancedStatsView.body`, the G124 successor of the Usage views), which — like
    /// `isEmptyRange` — requires `errorMessage == nil`.
    func testShowsProgressClearsAfterAFailedRangeFetchSoTheErrorCanRender() async throws {
        struct Boom: Error {}
        let vm = UsageViewModel(store: Store(cache: tempCache(), api: FakeSyncAPI())) { _ in throw Boom() }

        vm.range = "30d"
        try await Task.sleep(for: .milliseconds(120))

        XCTAssertNotNil(vm.errorMessage)
        XCTAssertFalse(vm.isLoadingRange, "the failed attempt must not leave isLoadingRange stuck")
        XCTAssertFalse(vm.showsProgress, "a failed fetch is a finished attempt — it must not spin forever")
    }

    /// The month (default) range shares the same bug: `load()` sets
    /// `errorMessage` on a failed fetch but never touches `store.consumption`,
    /// so `hasLoadedSelectedRange` stays false forever too — `showsProgress`
    /// must clear here for the same reason.
    func testShowsProgressClearsAfterAFailedMonthLoad() async throws {
        let api = FakeSyncAPI()
        api.replies[.consumption] = .failure
        let store = Store(cache: tempCache(), api: api)
        let vm = UsageViewModel(store: store)

        await vm.load()

        XCTAssertNotNil(vm.errorMessage)
        XCTAssertNil(store.consumption.value)
        XCTAssertFalse(vm.showsProgress, "a failed month load is a finished attempt — it must not spin forever")
    }
}
