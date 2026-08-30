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
            Task { await loadRange() }
        }
    }

    var selectedDay: CalendarDay?
    var isLoadingRange = false
    var errorMessage: String?

    private var rangeSummary: ConsumptionSummary?
    private var rangeStats: ConsumptionStats?
    private var rangeConnections: [ConnectionConsumption]?

    init(store: Store) {
        self.store = store
        mode = UsageMode(rawValue: UserDefaults.standard.string(forKey: "cicada.usageMode") ?? "") ?? .minimal
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

    /// Direct, uncached fetch for a non-default range. Never touches the
    /// Store or its disk cache — only the "month" default view is shared
    /// across launches and reconciled live.
    private func loadRange() async {
        guard range != "month" else {
            rangeSummary = nil
            rangeStats = nil
            rangeConnections = nil
            return
        }
        isLoadingRange = true
        defer { isLoadingRange = false }
        errorMessage = nil
        do {
            let api = APIClient.shared
            async let s = api.fetchConsumptionSummary(range: range)
            async let st = api.fetchConsumptionStats(range: range)
            async let c = api.fetchConsumptionConnections(range: range)
            let (summary, stats, connections) = try await (s, st, c)
            rangeSummary = summary
            rangeStats = stats
            rangeConnections = connections.connections
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
