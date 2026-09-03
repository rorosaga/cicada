import Foundation

struct Snapshot<T: Codable> {
    var value: T? = nil
    var etag: String? = nil
    var loadedAt: Date? = nil
    var isRefreshing = false
    var isEmpty: Bool { value == nil }
}

enum SyncDomain: String, CaseIterable, Codable {
    case graph, inbox, banks, sources, channels, feeds, calendars, contributors, origins, connections, status
    /// Usage dashboard (G51). Machine-global like `banks` — cached under
    /// `Store.rosterBank`, not the active bank — so switching banks doesn't
    /// blank the dashboard (per-bank breakdowns live inside the payload).
    case consumption
    /// Per-bank Ask (G52) history. Persisted via `SnapshotCache` like every
    /// other domain, but it has no server-side counterpart — nothing to GET,
    /// no etag, no version-vector mapping — so `Store.refresh`/`refreshAll`
    /// skip it explicitly (see the `case .askHistory: continue` there).
    case askHistory
    /// G124 — one card per memory source (`GET /sources/overview`). Per-bank;
    /// rides the `episodes`, `entities` and `sources` version-vector
    /// components — exactly the files its ETag covers (R7, ship-together).
    case sourcesOverview
}
