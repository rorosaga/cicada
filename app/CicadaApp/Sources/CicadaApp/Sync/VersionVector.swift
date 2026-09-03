import Foundation

struct VersionVector: Codable, Equatable {
    let version: String
    let components: [String: String]

    static let mapping: [String: Set<SyncDomain>] = [
        // `sourcesOverview` (G124 R7) rides `entities`, `episodes` and
        // `sources` — the three components its ETag is computed from.
        "entities": [.graph, .contributors, .origins, .sourcesOverview], "edges": [.graph, .contributors, .origins], "hubs": [.graph, .contributors, .origins],
        "inbox": [.inbox, .graph, .status], "episodes": [.status, .origins, .sources, .channels, .sourcesOverview],
        // The `sources` component folds in `feeds.yaml`, `calendars.yaml` and
        // `sync_state.json` (see `sync_service.components`), so the feed,
        // calendar and capture-channel lists all ride it.
        "sources": [.sources, .feeds, .calendars, .channels, .sourcesOverview], "git_head": [.contributors], "sleep": [.status],
        // The logo cache sits outside the bank; a Sleep warm-up or an on-demand
        // fetch changes `/graph`'s `hasLogo` and nothing else, so it needs its
        // own key or the node keeps painting a monogram.
        "logos": [.graph],
        // The telemetry ledger and the consumption endpoints' etags all move
        // together with the current `events-YYYY-MM.jsonl` mtime (see
        // `sync_service.components`'s "telemetry" key) — one component so the
        // dashboard live-refreshes off SSE instead of going stale until a
        // bank write happens to touch a different component.
        "telemetry": [.consumption],
    ]

    func changedDomains(since old: VersionVector?) -> Set<SyncDomain> {
        guard let old else { return Set(SyncDomain.allCases) }
        if old.version == version { return [] }
        if components["bank"] != old.components["bank"] { return Set(SyncDomain.allCases) }
        var out = Set<SyncDomain>()
        for (key, domains) in Self.mapping where components[key] != old.components[key] { out.formUnion(domains) }
        return out
    }
}
