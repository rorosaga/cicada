import Foundation
import Observation
import SwiftUI

enum UsageMode: String, CaseIterable { case minimal = "Minimal", advanced = "Advanced" }

/// Thin projection over `Store.consumption` (§5.1/§5.5), mirroring
/// `ConnectionsViewModel`. The Store's default view (range "month", 53-week
/// calendar) hydrates from disk and reconciles off the `"telemetry"`
/// version-vector component; switching the range picker away from "month"
/// does a direct, uncached fetch (like `ConnectionsViewModel`'s `fresh: true`
/// probe) rather than growing the Store's single sync domain into a
/// per-range cache.
@Observable
@MainActor
final class UsageViewModel {
    private let store: Store

    var mode: UsageMode {
        didSet { UserDefaults.standard.set(mode.rawValue, forKey: "cicada.usageMode") }
    }

    /// "month" reads straight from the Store; anything else triggers
    /// `loadRange()` and reads from the `range*` overrides below.
    var range = "month" {
        didSet {
            guard range != oldValue else { return }
            // Cooperative cancellation on top of the `rangeToken` identity
            // check in `loadRange()`: a slow URLSession task (or, in tests, a
            // parked continuation) doesn't unwind on its own just because a
            // newer range superseded it, so the token check alone is the
            // real backstop — but cancelling here still frees the in-flight
            // work the moment it's abandoned instead of leaving it to run to
            // completion for nothing.
            rangeTask?.cancel()
            rangeTask = Task { await self.loadRange() }
        }
    }

    var selectedDay: CalendarDay?
    var isLoadingRange = false
    var errorMessage: String?

    private var rangeSummary: ConsumptionSummary?
    private var rangeStats: ConsumptionStats?
    private var rangeConnections: [ConnectionConsumption]?

    /// Fetches summary + stats + connections for one non-default range.
    /// Injectable so the cancel-and-guard behaviour is testable without a
    /// live backend.
    typealias RangeFetch = (String) async throws -> (ConsumptionSummary, ConsumptionStats, ConsumptionConnections)

    private let rangeFetch: RangeFetch

    /// Handle of the in-flight `loadRange()` Task — cancelled the instant a
    /// newer range change supersedes it (see `range`'s `didSet`).
    private var rangeTask: Task<Void, Never>?

    /// Bumped by every range change. A response whose token no longer matches
    /// lost the race and is dropped — otherwise a slow "30 days" landing after
    /// a fast "90 days" repaints September's totals under a 90-day label.
    private var rangeToken = 0

    init(store: Store, rangeFetch: @escaping RangeFetch = UsageViewModel.liveRangeFetch) {
        self.store = store
        self.rangeFetch = rangeFetch
        mode = UsageMode(rawValue: UserDefaults.standard.string(forKey: "cicada.usageMode") ?? "") ?? .minimal
    }

    // `nonisolated(unsafe)`: a default-argument expression is evaluated in a
    // nonisolated context even though `init` itself is `@MainActor`, so a
    // plain main-actor-isolated `static let` here can't be referenced as the
    // default for `rangeFetch` below. The closure captures nothing mutable —
    // it just awaits three actor-hopping `APIClient` calls — so there is
    // nothing to race.
    nonisolated(unsafe) static let liveRangeFetch: RangeFetch = { range in
        let api = APIClient.shared
        async let s = api.fetchConsumptionSummary(range: range)
        async let st = api.fetchConsumptionStats(range: range)
        async let c = api.fetchConsumptionConnections(range: range)
        return try await (s, st, c)
    }

    // MARK: - Projections

    var summary: ConsumptionSummary {
        range == "month" ? (store.consumption.value?.summary ?? ConsumptionSummary()) : (rangeSummary ?? ConsumptionSummary())
    }

    /// The heatmap always shows the default 53-week calendar — it isn't
    /// range-scoped the way summary/stats/connections are.
    var calendar: [CalendarDay] { store.consumption.value?.calendar.days ?? [] }

    var stats: ConsumptionStats? {
        range == "month" ? store.consumption.value?.stats : rangeStats
    }

    var connections: [ConnectionConsumption] {
        range == "month" ? (store.consumption.value?.connections.connections ?? []) : (rangeConnections ?? [])
    }

    var harness: HarnessStats? { store.consumption.value?.harness }

    var isLoading: Bool { store.consumption.isEmpty && store.consumption.isRefreshing }

    /// Whether the data backing the *currently selected* range has actually
    /// landed at least once. `summary`'s zero-valued fallback (`ConsumptionSummary()`
    /// above) reads identically to a confirmed all-zero range, so without this
    /// `isEmptyRange` treated "nothing has loaded yet" — e.g. before
    /// `Store.bootstrap()` ever populates `store.consumption`, or before the
    /// first `loadRange()` response for a non-default range lands — as a
    /// confirmed empty month, and the page briefly claimed "No usage this
    /// month" for data it had simply never asked about yet.
    private var hasLoadedSelectedRange: Bool {
        range == "month" ? store.consumption.value != nil : rangeSummary != nil
    }

    /// Nothing was recorded in this range. Drives the "No usage in this range"
    /// placeholders — a row of honest zeroes reads as a broken page.
    /// M2: a failed fetch also leaves `summary` all-zero (`ConsumptionSummary()`
    /// above), so without the `errorMessage == nil` guard a failed range fetch
    /// rendered both the error banner AND "No usage in this range" — claiming
    /// a fact about a range that was never actually loaded.
    var isEmptyRange: Bool {
        hasLoadedSelectedRange
            && !isLoading && !isLoadingRange && errorMessage == nil
            && summary.invocations == 0 && summary.tokens == 0 && summary.memoryWrites == 0
    }

    /// Flat monthly price of every connected subscription, or nil when none.
    var subscriptionUsdMonth: Double? {
        let prices = connections.filter { $0.billing == "subscription" && $0.connected }.compactMap(\.priceUsdMonth)
        return prices.isEmpty ? nil : prices.reduce(0, +)
    }

    var costLine: String {
        UsageFormat.costLine(costUsd: summary.costUsd, equivUsd: summary.equivCostUsd, subscriptionUsd: subscriptionUsdMonth)
    }

    // MARK: - Loading

    /// Reconciles the Store's default view. Views call this from `.task`;
    /// the Store itself already hydrates from disk before this ever runs, so
    /// the page never opens blank even offline.
    func load() async {
        errorMessage = nil
        await store.refresh([.consumption])
        if store.consumption.value == nil {
            errorMessage = store.toast
        }
    }

    /// Direct, uncached fetch for a non-default range. Never touches the Store
    /// or its disk cache — only the "month" default view is shared across
    /// launches and reconciled live.
    private func loadRange() async {
        rangeToken &+= 1
        let token = rangeToken

        // Blank first, in both directions: showing the previous range's
        // numbers under the new label for a whole round-trip is worse than
        // showing a spinner.
        rangeSummary = nil
        rangeStats = nil
        rangeConnections = nil
        errorMessage = nil

        guard range != "month" else {
            isLoadingRange = false
            return
        }

        isLoadingRange = true
        do {
            let (summary, stats, connections) = try await rangeFetch(range)
            // A newer range owns the view (and the loading flag) now — this
            // response lost the race, whether because it was cancelled above
            // or because it simply arrived after a faster one.
            guard token == rangeToken, !Task.isCancelled else { return }
            rangeSummary = summary
            rangeStats = stats
            rangeConnections = connections.connections
        } catch {
            guard token == rangeToken, !Task.isCancelled else { return }
            errorMessage = error.localizedDescription
        }
        isLoadingRange = false
    }
}
