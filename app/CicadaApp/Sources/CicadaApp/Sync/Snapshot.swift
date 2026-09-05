import Foundation

struct Snapshot<T: Codable> {
    var value: T? = nil
    var etag: String? = nil
    /// When this value entered memory — **including a hydrate off the disk
    /// cache**. It is a change token, not a freshness claim: `GraphViewModel`
    /// compares it against `lastSyncedLoadedAt` to decide whether to re-map
    /// the graph, so a hydrate has to move it or a cold-launched graph would
    /// never be drawn.
    var loadedAt: Date? = nil
    /// When the BACKEND last confirmed this value — set only where a network
    /// response landed (a 200 with a new body, or a 304 saying the body we
    /// hold is still current). A disk hydrate explicitly clears it.
    ///
    /// G125 v3 Task 8, review round 2. The Sleep page's `as of HH:MM` chip
    /// dates the page when the backend is unreachable, and it was reading
    /// `loadedAt` — which a cold launch with the backend stopped stamps with
    /// the launch time. The chip then printed the minute the app opened over
    /// data that could be days old: exactly the fabricated timestamp
    /// `sleepLiveness` refuses to print, in the one state the feature exists
    /// for. Splitting the two keeps `loadedAt`'s change-token job intact and
    /// gives a reader a field that means what the chip claims. `nil` means
    /// "the backend has never confirmed this in this session" — a refusal to
    /// date the page, not a zero.
    var refreshedAt: Date? = nil
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
