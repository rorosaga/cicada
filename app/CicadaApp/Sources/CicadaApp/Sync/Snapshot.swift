import Foundation

struct Snapshot<T: Codable> {
    var value: T? = nil
    var etag: String? = nil
    var loadedAt: Date? = nil
    var isRefreshing = false
    var isEmpty: Bool { value == nil }
}

enum SyncDomain: String, CaseIterable, Codable {
    case graph, inbox, banks, sources, feeds, calendars, contributors, origins, connections, status
    /// Per-bank Ask (G52) history. Persisted via `SnapshotCache` like every
    /// other domain, but it has no server-side counterpart — nothing to GET,
    /// no etag, no version-vector mapping — so `Store.refresh`/`refreshAll`
    /// skip it explicitly (see the `case .askHistory: continue` there).
    case askHistory
}
